from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime
from core.database import get_db
from core.models import ReferralCode, ReferralRecord, UserCredit
from stripe_manager.referral_manager.utils import generate_unique_code, get_code_expiry_date
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe Referral Code Management"])


class GetCodeRequest(BaseModel):
    user_id: str


class ReferralStatsResponse(BaseModel):
    user_id: str
    referral_code: str
    total_referrals: int
    completed_referrals: int
    pending_referrals: int
    total_credits_earned: float
    code_expires_at: datetime = None
    is_active: bool


@router.post("/my-code")
async def get_or_create_referral_code(
    request: GetCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    获取用户的邀请码，如果不存在则自动生成
    
    返回用户的邀请码和过期时间
    """
    try:
        user_id = request.user_id
        logger.info(f"Getting referral code for user_id: {user_id}")
        
        # 查询是否已有邀请码
        stmt = select(ReferralCode).where(ReferralCode.user_id == user_id)
        result = await db.execute(stmt)
        existing_code = result.scalar_one_or_none()
        
        if existing_code:
            logger.info(f"Found existing code: {existing_code.referral_code}")
            return {
                "message": "Referral code retrieved",
                "data": {
                    "referral_code": existing_code.referral_code,
                    "is_active": existing_code.is_active,
                    "expires_at": existing_code.expires_at,
                    "created_at": existing_code.created_at
                },
                "status": "success"
            }
        
        # 生成新邀请码
        new_code = await generate_unique_code(db)
        expires_at = get_code_expiry_date(days=365)  # 1年有效期
        
        referral_code = ReferralCode(
            user_id=user_id,
            referral_code=new_code,
            is_active=True,
            expires_at=expires_at
        )
        
        db.add(referral_code)
        await db.commit()
        await db.refresh(referral_code)
        
        logger.info(f"Generated new referral code: {new_code} for user_id: {user_id}")
        
        return {
            "message": "Referral code generated successfully",
            "data": {
                "referral_code": referral_code.referral_code,
                "is_active": referral_code.is_active,
                "expires_at": referral_code.expires_at,
                "created_at": referral_code.created_at
            },
            "status": "success"
        }
        
    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to get/create referral code: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stats")
async def get_referral_stats(
    request: GetCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    查看推荐统计信息
    
    返回：
    - 总邀请人数
    - 已完成返利人数
    - 待付费人数
    - 累计返利金额
    """
    try:
        user_id = request.user_id
        logger.info(f"Getting referral stats for user_id: {user_id}")
        
        # 查询邀请码
        stmt_code = select(ReferralCode).where(ReferralCode.user_id == user_id)
        result_code = await db.execute(stmt_code)
        referral_code_obj = result_code.scalar_one_or_none()
        
        if not referral_code_obj:
            raise HTTPException(
                status_code=404,
                detail="No referral code found. Please generate one first."
            )
        
        # 统计推荐记录
        stmt_total = select(func.count(ReferralRecord.id)).where(
            ReferralRecord.referrer_user_id == user_id
        )
        result_total = await db.execute(stmt_total)
        total_referrals = result_total.scalar()
        
        stmt_completed = select(func.count(ReferralRecord.id)).where(
            ReferralRecord.referrer_user_id == user_id,
            ReferralRecord.status == 'completed'
        )
        result_completed = await db.execute(stmt_completed)
        completed_referrals = result_completed.scalar()
        
        stmt_pending = select(func.count(ReferralRecord.id)).where(
            ReferralRecord.referrer_user_id == user_id,
            ReferralRecord.status == 'pending'
        )
        result_pending = await db.execute(stmt_pending)
        pending_referrals = result_pending.scalar()
        
        # 查询用户余额
        stmt_credit = select(UserCredit).where(UserCredit.user_id == user_id)
        result_credit = await db.execute(stmt_credit)
        user_credit = result_credit.scalar_one_or_none()
        
        total_credits_earned = float(user_credit.total_credits) if user_credit else 0.0
        
        logger.info(f"Stats retrieved for user_id: {user_id}")
        
        return {
            "message": "Referral stats retrieved successfully",
            "data": {
                "user_id": user_id,
                "referral_code": referral_code_obj.referral_code,
                "total_referrals": total_referrals,
                "completed_referrals": completed_referrals,
                "pending_referrals": pending_referrals,
                "total_credits_earned": total_credits_earned,
                "code_expires_at": referral_code_obj.expires_at,
                "is_active": referral_code_obj.is_active
            },
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get referral stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))