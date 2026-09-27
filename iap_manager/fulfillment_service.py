"""Apple 购买入账 / 退款回滚 / 订阅状态刷新

三种商品：
  subscription  ReceiptTalk Plus 月订阅 → subscription_status='pro'，receipt month_limit=100
                                          语音 100 分钟/月由 Edge Function 按 plan 给
  receipt_pack  100 张 receipt（一次性）→ raw_limit += 100（永久池，和 Stripe 流量包一致）
  voice_pack    100 分钟语音（一次性）  → aivoice_balance.pack_seconds += 6000

原则：
  - 幂等：iap_transactions.transaction_id 主键，同一笔交易只入账一次
  - 订阅状态从流水“推导”，不靠通知类型硬编码：
      有未撤销、未过期的订阅交易 → pro；否则（且当前 pro 来自这条 Apple 订阅）→ free
    这样通知乱序、重复、漏发都不会把状态搞错
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.models import (
    AivoiceBalance,
    IapTransaction,
    ReceiptUsageQuotaReceiptEn,
    ReceiptUsageQuotaRequestEn,
    UserLevelEn,
)
from iap_manager.apple_verifier import VerifiedTransaction

logger = logging.getLogger(__name__)

PLAN_MONTH_LIMIT = {"pro": 100, "team": 1000}
# 这些状态的权益 >= Plus，Apple 订阅不去覆盖它们
HIGHER_OR_EQUAL_STATUSES = {"team", "year_team", "year_pro"}
QUOTA_MODELS = (ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn)


class UnknownProductError(Exception):
    pass


def product_for(product_id: str) -> dict:
    product = settings.apple_product_map.get(product_id)
    if not product:
        raise UnknownProductError(f"Unknown Apple product: {product_id}")
    return product


# ---------------------------------------------------------------------
# 用户定位
# ---------------------------------------------------------------------
async def resolve_user_id(db: AsyncSession, tx: VerifiedTransaction) -> str | None:
    """appAccountToken 优先；其次看这条订阅链以前绑过谁；最后兼容旧的 apple_customer_id"""
    if tx.app_account_token:
        return tx.app_account_token

    row = await db.execute(
        select(IapTransaction.user_id)
        .where(IapTransaction.original_transaction_id == tx.original_transaction_id)
        .limit(1)
    )
    user_id = row.scalar_one_or_none()
    if user_id:
        return str(user_id)

    row = await db.execute(
        select(UserLevelEn.user_id).where(UserLevelEn.apple_customer_id == tx.original_transaction_id)
    )
    user_id = row.scalar_one_or_none()
    return str(user_id) if user_id else None


# ---------------------------------------------------------------------
# 入账
# ---------------------------------------------------------------------
async def fulfill_transaction(db: AsyncSession, tx: VerifiedTransaction, user_id: str) -> dict:
    product = product_for(tx.product_id)

    if tx.revoked_at:
        return await revoke_transaction(db, tx, user_id)

    receipts = product.get("receipts", 0)
    seconds = product.get("seconds", 0)

    inserted = await db.execute(
        pg_insert(IapTransaction)
        .values(
            transaction_id=tx.transaction_id,
            original_transaction_id=tx.original_transaction_id,
            user_id=user_id,
            product_id=tx.product_id,
            product_type=product["type"],
            bundle_id=tx.bundle_id,
            environment=tx.environment,
            purchased_at=tx.purchased_at,
            expires_at=tx.expires_at,
            receipts_added=receipts,
            voice_seconds_added=seconds,
        )
        .on_conflict_do_nothing(index_elements=["transaction_id"])
        .returning(IapTransaction.transaction_id)
    )
    is_new = inserted.scalar_one_or_none() is not None

    if product["type"] == "subscription":
        status = await refresh_subscription_state(db, user_id)
        await db.commit()
        return {"product_type": "subscription", "new": is_new, "subscription_status": status}

    if is_new and product["type"] == "receipt_pack":
        await _add_receipts(db, user_id, receipts)
    elif is_new and product["type"] == "voice_pack":
        await _add_voice_seconds(db, user_id, seconds)

    await db.commit()
    logger.info(
        f"[IAP] fulfilled tx={tx.transaction_id} user={user_id} product={tx.product_id} new={is_new}"
    )
    return {
        "product_type": product["type"],
        "new": is_new,
        "receipts_added": receipts if is_new else 0,
        "voice_seconds_added": seconds if is_new else 0,
    }


# ---------------------------------------------------------------------
# 退款 / 撤销
# ---------------------------------------------------------------------
async def revoke_transaction(db: AsyncSession, tx: VerifiedTransaction, user_id: str) -> dict:
    product = product_for(tx.product_id)
    revoked_at = tx.revoked_at or datetime.now(timezone.utc)

    row = (await db.execute(
        select(IapTransaction).where(IapTransaction.transaction_id == tx.transaction_id).with_for_update()
    )).scalar_one_or_none()

    if row is None:
        # 从没入过账就被退款：只记一条，不发也不扣
        db.add(IapTransaction(
            transaction_id=tx.transaction_id,
            original_transaction_id=tx.original_transaction_id,
            user_id=user_id,
            product_id=tx.product_id,
            product_type=product["type"],
            bundle_id=tx.bundle_id,
            environment=tx.environment,
            purchased_at=tx.purchased_at,
            expires_at=tx.expires_at,
            revoked_at=revoked_at,
            receipts_added=0,
            voice_seconds_added=0,
        ))
    elif row.revoked_at is None:
        row.revoked_at = revoked_at
        if row.product_type == "receipt_pack" and row.receipts_added:
            await _add_receipts(db, str(row.user_id), -row.receipts_added)
        elif row.product_type == "voice_pack" and row.voice_seconds_added:
            await _add_voice_seconds(db, str(row.user_id), -row.voice_seconds_added)

    await db.flush()  # session 关了 autoflush，下面的查询要能看到 revoked_at
    status = None
    if product["type"] == "subscription":
        status = await refresh_subscription_state(db, user_id)

    await db.commit()
    logger.info(f"[IAP] revoked tx={tx.transaction_id} user={user_id} product={tx.product_id}")
    return {"product_type": product["type"], "revoked": True, "subscription_status": status}


async def unrevoke_transaction(db: AsyncSession, tx: VerifiedTransaction, user_id: str) -> dict:
    """REFUND_REVERSED：Apple 撤回了退款，把权益加回来"""
    row = (await db.execute(
        select(IapTransaction).where(IapTransaction.transaction_id == tx.transaction_id).with_for_update()
    )).scalar_one_or_none()

    if row is None or row.revoked_at is None:
        return await fulfill_transaction(db, tx, user_id)

    row.revoked_at = None
    product = product_for(tx.product_id)
    if product["type"] == "receipt_pack":
        row.receipts_added = product["receipts"]
        await _add_receipts(db, str(row.user_id), product["receipts"])
    elif product["type"] == "voice_pack":
        row.voice_seconds_added = product["seconds"]
        await _add_voice_seconds(db, str(row.user_id), product["seconds"])

    await db.flush()
    status = await refresh_subscription_state(db, user_id) if product["type"] == "subscription" else None
    await db.commit()
    return {"product_type": product["type"], "reinstated": True, "subscription_status": status}


# ---------------------------------------------------------------------
# 订阅状态：从流水推导
# ---------------------------------------------------------------------
async def refresh_subscription_state(db: AsyncSession, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    active = (await db.execute(
        select(IapTransaction.original_transaction_id)
        .where(
            IapTransaction.user_id == user_id,
            IapTransaction.product_type == "subscription",
            IapTransaction.revoked_at.is_(None),
            IapTransaction.expires_at > now,
        )
        .order_by(IapTransaction.expires_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    user = (await db.execute(
        select(UserLevelEn.subscription_status, UserLevelEn.apple_customer_id)
        .where(UserLevelEn.user_id == user_id)
    )).first()
    if user is None:
        logger.warning(f"[IAP] user_level_en row missing for user={user_id}")
        return "unknown"

    current = (user.subscription_status or "free").lower()

    if active:
        if current in HIGHER_OR_EQUAL_STATUSES:
            # 已有 team / 年付，不降级它们，只记下 Apple 订阅链
            await db.execute(
                update(UserLevelEn).where(UserLevelEn.user_id == user_id)
                .values(apple_customer_id=active)
            )
            return current
        await _set_plan(db, user_id, "pro", apple_customer_id=active)
        return "pro"

    # 没有有效 Apple 订阅：只有当前 pro 确实来自 Apple 时才降级，避免误伤 Stripe 用户
    all_apple_chains = (await db.execute(
        select(IapTransaction.original_transaction_id)
        .where(IapTransaction.user_id == user_id, IapTransaction.product_type == "subscription")
        .distinct()
    )).scalars().all()
    pro_from_apple = current == "pro" and user.apple_customer_id in set(all_apple_chains)

    if pro_from_apple:
        await _set_plan(db, user_id, "free")
        return "free"
    return current


async def _set_plan(db: AsyncSession, user_id: str, plan: str, apple_customer_id: str | None = None):
    values = {"subscription_status": plan}
    if apple_customer_id:
        values["apple_customer_id"] = apple_customer_id
    await db.execute(update(UserLevelEn).where(UserLevelEn.user_id == user_id).values(**values))

    month_limit = PLAN_MONTH_LIMIT.get(plan, 0)
    for model in QUOTA_MODELS:
        await db.execute(update(model).where(model.user_id == user_id).values(month_limit=month_limit))
    logger.info(f"[IAP] user={user_id} plan={plan} month_limit={month_limit}")


# ---------------------------------------------------------------------
# 额度增减
# ---------------------------------------------------------------------
async def _add_receipts(db: AsyncSession, user_id: str, delta: int):
    """receipt 包：加进 raw_limit（永久池），逻辑同 Stripe fulfill_credit_pack；退款时 delta 为负"""
    for model in QUOTA_MODELS:
        await db.execute(
            update(model)
            .where(model.user_id == user_id)
            .values(raw_limit=func.greatest(func.coalesce(model.raw_limit, 0) + delta, 0))
        )


async def _add_voice_seconds(db: AsyncSession, user_id: str, delta: int):
    """语音包：加进 aivoice_balance.pack_seconds；退款时 delta 为负（已用掉的扣到 0 为止）"""
    stmt = pg_insert(AivoiceBalance).values(user_id=user_id, pack_seconds=max(delta, 0))
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "pack_seconds": func.greatest(AivoiceBalance.pack_seconds + delta, 0),
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)
