import logging
from datetime import datetime, timezone
from sqlalchemy import select, update
from core.database import AsyncSessionLocal
from core.models import (
    UserAnnualSubscription,
    UserLevelEn,
    ReceiptUsageQuotaReceiptEn,
    ReceiptUsageQuotaRequestEn,
)

logger = logging.getLogger(__name__)

ANNUAL_LIMIT_BY_PLAN = {"pro": 1200, "team": 20000}


async def do_check_annual_expiry():
    """
    每日跑一次：
    1. 到期的active记录 -> expired，该用户 annual_limit/used_annual 清零
    2. 若该用户有排队中的下一条(starts_at<=now) -> 激活它，写入新额度+身份标签
    3. 若没有排队的了 -> 仅当subscription_status仍是year_xxx时才降级为free
       （避免覆盖用户后续办理的月付订阅）
    raw_limit / month_limit / used_month 全程不动
    """
    async with AsyncSessionLocal() as db:
        try:
            now = datetime.now(timezone.utc)

            stmt = select(UserAnnualSubscription).where(
                UserAnnualSubscription.status == "active",
                UserAnnualSubscription.expires_at <= now,
            )
            result = await db.execute(stmt)
            expired_rows = result.scalars().all()
            logger.info(f"Found {len(expired_rows)} expired annual subscriptions")

            for row in expired_rows:
                row.status = "expired"

                for model in (ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn):
                    await db.execute(
                        update(model)
                        .where(model.user_id == row.user_id)
                        .values(annual_limit=0, used_annual=0)
                    )

                stmt_next = (
                    select(UserAnnualSubscription)
                    .where(
                        UserAnnualSubscription.user_id == row.user_id,
                        UserAnnualSubscription.status == "queued",
                        UserAnnualSubscription.starts_at <= now,
                    )
                    .order_by(UserAnnualSubscription.starts_at.asc())
                )
                result_next = await db.execute(stmt_next)
                next_row = result_next.scalars().first()

                if next_row:
                    next_row.status = "active"
                    annual_amount = ANNUAL_LIMIT_BY_PLAN[next_row.plan]
                    status_label = f"year_{next_row.plan}"

                    for model in (ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn):
                        await db.execute(
                            update(model)
                            .where(model.user_id == row.user_id)
                            .values(annual_limit=annual_amount, used_annual=0)
                        )
                    await db.execute(
                        update(UserLevelEn)
                        .where(UserLevelEn.user_id == row.user_id)
                        .values(subscription_status=status_label)
                    )
                    logger.info(f"Promoted queued annual sub for user_id={row.user_id}, plan={next_row.plan}")
                else:
                    stmt_user = select(UserLevelEn.subscription_status).where(
                        UserLevelEn.user_id == row.user_id
                    )
                    result_user = await db.execute(stmt_user)
                    current_status = result_user.scalar_one_or_none()

                    if current_status == f"year_{row.plan}":
                        await db.execute(
                            update(UserLevelEn)
                            .where(UserLevelEn.user_id == row.user_id)
                            .values(subscription_status="free")
                        )
                        logger.info(f"Downgraded user_id={row.user_id} to free (annual expired)")

            await db.commit()
            logger.info("Annual expiry check completed")

        except Exception as e:
            await db.rollback()
            logger.error(f"Annual expiry check failed: {e}")