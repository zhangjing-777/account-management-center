import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import AnnualRedeemCode
from stripe_manager.annual_manager.utils import generate_unique_annual_code

logger = logging.getLogger(__name__)


async def generate_annual_code(
    db: AsyncSession,
    session_id: str,
    plan: str,
    purchaser_email_hash: str,
    purchaser_user_id: str = None,
) -> str:
    """
    Stripe one-off支付成功后生成年度激活码（此时还未绑定实际使用人）
    幂等：同一个 stripe_checkout_session_id 只生成一次，防止webhook重试重复生成
    """
    stmt = select(AnnualRedeemCode).where(
        AnnualRedeemCode.stripe_checkout_session_id == session_id
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        logger.info(f"Annual code already generated for session {session_id}, skip")
        return existing.code

    code = await generate_unique_annual_code(db)

    db.add(
        AnnualRedeemCode(
            code=code,
            plan=plan,
            stripe_checkout_session_id=session_id,
            purchaser_email_hash=purchaser_email_hash,
            purchaser_user_id=purchaser_user_id,
            status="unused",
        )
    )
    await db.commit()
    logger.info(f"Generated annual code {code} for plan={plan}, session={session_id}")
    return code