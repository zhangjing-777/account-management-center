import logging
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import CreditPackPurchase, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn

logger = logging.getLogger(__name__)


async def fulfill_credit_pack(db: AsyncSession, session_id: str, user_id: str, credits: int):
    """
    流量包直充：额度加进 raw_limit（永久福利池，逻辑同新用户送的50张，不限时）
    幂等：同一个 stripe_checkout_session_id 只入账一次，防止webhook重试重复加钱
    """
    stmt = select(CreditPackPurchase).where(
        CreditPackPurchase.stripe_checkout_session_id == session_id
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        logger.info(f"Credit pack for session {session_id} already fulfilled, skip")
        return

    for model in (ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn):
        await db.execute(
            update(model)
            .where(model.user_id == user_id)
            .values(raw_limit=model.raw_limit + credits)
        )

    db.add(
        CreditPackPurchase(
            stripe_checkout_session_id=session_id,
            user_id=user_id,
            pack_size=credits,
            credits_added=credits,
        )
    )
    await db.commit()
    logger.info(f"Fulfilled credit pack: user_id={user_id}, credits={credits}, session={session_id}")