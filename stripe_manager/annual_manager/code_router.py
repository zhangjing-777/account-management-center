from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
import logging

from core.database import get_db
from core.models import (
    AnnualRedeemCode,
    UserAnnualSubscription,
    UserLevelEn,
    ReceiptUsageQuotaReceiptEn,
    ReceiptUsageQuotaRequestEn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe Annual Code Management"])

ANNUAL_LIMIT_BY_PLAN = {"pro": 1200, "team": 20000}
ANNUAL_DAYS = 365


class RedeemAnnualCodeRequest(BaseModel):
    user_id: str
    code: str


@router.get("/annual-code-by-session")
async def get_annual_code_by_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    支付成功页用 session_id 查询对应的激活码。
    webhook是异步到达的，查不到时返回404，前端可做几次轮询重试。
    """
    stmt = select(AnnualRedeemCode).where(
        AnnualRedeemCode.stripe_checkout_session_id == session_id
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Code not ready yet, please retry shortly")

    return {
        "message": "Annual code retrieved",
        "data": {"code": record.code, "plan": record.plan, "status": record.status},
        "status": "success",
    }


async def _activate_now(db: AsyncSession, user_id: str, plan: str):
    """把当前生效的年度订阅额度写入配额表 + 更新身份标签"""
    annual_amount = ANNUAL_LIMIT_BY_PLAN[plan]
    status_label = f"year_{plan}"  # year_pro / year_team

    for model in (ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn):
        await db.execute(
            update(model)
            .where(model.user_id == user_id)
            .values(annual_limit=annual_amount, used_annual=0)
        )

    await db.execute(
        update(UserLevelEn)
        .where(UserLevelEn.user_id == user_id)
        .values(subscription_status=status_label)
    )
    logger.info(f"Activated annual plan={plan} for user_id={user_id}")


@router.post("/redeem-annual-code")
async def redeem_annual_code(request: RedeemAnnualCodeRequest, db: AsyncSession = Depends(get_db)):
    """
    兑换年度激活码
    - 一个code只能被使用一次
    - 同一用户可连续兑换多个code，按兑换顺序排队续期，不叠加，逐年生效
    """
    try:
        user_id = request.user_id
        code = request.code.upper().strip()

        stmt_code = select(AnnualRedeemCode).where(AnnualRedeemCode.code == code)
        result_code = await db.execute(stmt_code)
        code_obj = result_code.scalar_one_or_none()

        if not code_obj:
            raise HTTPException(status_code=404, detail="Invalid code")
        if code_obj.status != "unused":
            raise HTTPException(status_code=400, detail="Code has already been used")

        stmt_user = select(UserLevelEn).where(UserLevelEn.user_id == user_id)
        result_user = await db.execute(stmt_user)
        if not result_user.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")

        # 查该用户当前 active/queued 里最晚的到期时间，决定新记录排在哪
        stmt_last = (
            select(UserAnnualSubscription)
            .where(
                UserAnnualSubscription.user_id == user_id,
                UserAnnualSubscription.status.in_(["active", "queued"]),
            )
            .order_by(UserAnnualSubscription.expires_at.desc())
        )
        result_last = await db.execute(stmt_last)
        last_sub = result_last.scalars().first()

        now = datetime.now(timezone.utc)
        if last_sub:
            starts_at = last_sub.expires_at
            status = "queued"
        else:
            starts_at = now
            status = "active"

        expires_at = starts_at + timedelta(days=ANNUAL_DAYS)

        db.add(
            UserAnnualSubscription(
                user_id=user_id,
                plan=code_obj.plan,
                source_code=code,
                redeemed_at=now,
                starts_at=starts_at,
                expires_at=expires_at,
                status=status,
            )
        )

        code_obj.status = "used"
        code_obj.redeemed_by_user_id = user_id
        code_obj.redeemed_at = now

        if status == "active":
            await _activate_now(db, user_id, code_obj.plan)

        await db.commit()

        logger.info(
            f"Code {code} redeemed by user_id={user_id}, plan={code_obj.plan}, "
            f"status={status}, starts_at={starts_at}, expires_at={expires_at}"
        )

        return {
            "message": "Annual code redeemed successfully",
            "data": {"plan": code_obj.plan, "status": status, "starts_at": starts_at, "expires_at": expires_at},
            "status": "success",
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to redeem annual code: {e}")
        raise HTTPException(status_code=500, detail=str(e))