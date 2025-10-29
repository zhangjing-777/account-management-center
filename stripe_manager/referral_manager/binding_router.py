from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime, timezone
from core.database import get_db
from core.models import UserLevelEn, ReferralCode, ReferralRecord
from stripe_manager.referral_manager.utils import is_code_expired
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe Referral Binding"])


class BindReferralRequest(BaseModel):
    user_id: str  # 被邀请人的 user_id
    referral_code: str  # 邀请码


@router.post("/bind")
async def bind_referral_code(
    request: BindReferralRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    绑定邀请码
    
    规则：
    1. 被邀请人只能绑定一次
    2. 不能使用自己的邀请码
    3. 邀请码必须有效且未过期
    4. 只能在首次付费前绑定
    """
    try:
        user_id = request.user_id
        referral_code = request.referral_code.upper().strip()
        
        logger.info(f"Binding referral code: {referral_code} for user_id: {user_id}")
        
        # 1. 检查被邀请人是否已经绑定过
        stmt_check_existing = select(ReferralRecord).where(
            ReferralRecord.referee_user_id == user_id
        )
        result_existing = await db.execute(stmt_check_existing)
        existing_binding = result_existing.scalar_one_or_none()
        
        if existing_binding:
            raise HTTPException(
                status_code=400,
                detail="You have already used a referral code"
            )
        
        # 2. 验证邀请码是否存在
        stmt_code = select(ReferralCode).where(
            ReferralCode.referral_code == referral_code
        )
        result_code = await db.execute(stmt_code)
        code_obj = result_code.scalar_one_or_none()
        
        if not code_obj:
            raise HTTPException(
                status_code=404,
                detail="Invalid referral code"
            )
        
        # 3. 检查邀请码是否有效
        if not code_obj.is_active:
            raise HTTPException(
                status_code=400,
                detail="Referral code is inactive"
            )
        
        # 4. 检查邀请码是否过期
        if code_obj.expires_at and is_code_expired(code_obj.expires_at):
            raise HTTPException(
                status_code=400,
                detail="Referral code has expired"
            )
        
        # 5. 不能使用自己的邀请码
        if code_obj.user_id == user_id:
            raise HTTPException(
                status_code=400,
                detail="You cannot use your own referral code"
            )
        
        # 6. 检查被邀请人是否已经付费（已经是Pro用户）
        stmt_user = select(UserLevelEn).where(UserLevelEn.user_id == user_id)
        result_user = await db.execute(stmt_user)
        user_obj = result_user.scalar_one_or_none()
        
        if not user_obj:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        if user_obj.subscription_status and user_obj.subscription_status.lower() == 'pro':
            raise HTTPException(
                status_code=400,
                detail="Cannot bind referral code after subscription"
            )
        
        # 7. 创建推荐记录
        referral_record = ReferralRecord(
            referrer_user_id=code_obj.user_id,
            referee_user_id=user_id,
            referral_code=referral_code,
            credit_amount=1.00,  # 1欧元返利
            status='pending'
        )
        
        db.add(referral_record)
        await db.commit()
        await db.refresh(referral_record)
        
        logger.info(f"Referral binding successful: referee={user_id}, "
                   f"referrer={code_obj.user_id}, code={referral_code}")
        
        return {
            "message": "Referral code bound successfully",
            "data": {
                "referee_user_id": user_id,
                "referrer_user_id": str(code_obj.user_id),
                "referral_code": referral_code,
                "status": "pending",
                "note": "You will receive rewards after the referred user's first payment"
            },
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to bind referral code: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-binding")
async def check_referral_binding(
    request: BindReferralRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    检查用户是否已绑定邀请码
    """
    try:
        user_id = request.user_id
        logger.info(f"Checking referral binding for user_id: {user_id}")
        
        stmt = select(ReferralRecord).where(
            ReferralRecord.referee_user_id == user_id
        )
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            return {
                "message": "No referral binding found",
                "data": None,
                "status": "success"
            }
        
        return {
            "message": "Referral binding found",
            "data": {
                "referrer_user_id": str(record.referrer_user_id),
                "referral_code": record.referral_code,
                "status": record.status,
                "created_at": record.created_at,
                "credited_at": record.credited_at
            },
            "status": "success"
        }
        
    except Exception as e:
        logger.exception(f"Failed to check referral binding: {e}")
        raise HTTPException(status_code=500, detail=str(e))