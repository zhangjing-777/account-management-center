"""
推荐返利核心业务逻辑

处理：
1. 检查是否有推荐关系
2. 验证是否首次付费
3. 计算返利金额
4. 更新推荐记录状态
5. 增加推荐人余额
6. 记录交易历史
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from decimal import Decimal
from core.models import UserLevelEn, ReferralRecord, UserCredit, CreditTransaction
import logging

logger = logging.getLogger(__name__)


async def process_referral_reward(
    db: AsyncSession,
    referee_user_id: str,
    stripe_customer_id: str = None
) -> dict:
    """
    处理推荐返利
    
    Args:
        db: 数据库会话
        referee_user_id: 被邀请人的user_id
        stripe_customer_id: Stripe客户ID（可选）
    
    Returns:
        返利处理结果字典
    """
    try:
        logger.info(f"Processing referral reward for referee_user_id: {referee_user_id}")
        
        # 1. 查询是否有待处理的推荐记录
        stmt = select(ReferralRecord).where(
            ReferralRecord.referee_user_id == referee_user_id,
            ReferralRecord.status == 'pending'
        )
        result = await db.execute(stmt)
        referral_record = result.scalar_one_or_none()
        
        if not referral_record:
            logger.info(f"No pending referral record found for user: {referee_user_id}")
            return {
                "processed": False,
                "reason": "no_pending_referral"
            }
        
        referrer_user_id = referral_record.referrer_user_id
        credit_amount = Decimal(str(referral_record.credit_amount))
        
        logger.info(f"Found referral: referrer={referrer_user_id}, "
                   f"referee={referee_user_id}, credit={credit_amount}")
        
        # 2. 验证被邀请人确实已升级为Pro
        stmt_user = select(UserLevelEn).where(UserLevelEn.user_id == referee_user_id,
                                              UserLevelEn.stripe_customer_id == stripe_customer_id)
        result_user = await db.execute(stmt_user)
        user_obj = result_user.scalar_one_or_none()
        
        if not user_obj:
            logger.warning(f"User {referee_user_id} is not Pro, skipping reward")
            return {
                "processed": False,
                "reason": "user_not_pro"
            }
        
        # 3. 更新或创建推荐人的余额记录
        stmt_credit = select(UserCredit).where(UserCredit.user_id == referrer_user_id)
        result_credit = await db.execute(stmt_credit)
        user_credit = result_credit.scalar_one_or_none()
        
        if user_credit:
            # 已存在余额记录，更新
            balance_before = user_credit.available_credits
            new_total = user_credit.total_credits + credit_amount
            new_available = user_credit.available_credits + credit_amount
            
            stmt_update_credit = (
                update(UserCredit)
                .where(UserCredit.user_id == referrer_user_id)
                .values(
                    total_credits=new_total,
                    available_credits=new_available,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.execute(stmt_update_credit)
            balance_after = new_available
            
        else:
            # 创建新余额记录
            balance_before = Decimal('0.00')
            user_credit = UserCredit(
                user_id=referrer_user_id,
                total_credits=credit_amount,
                used_credits=Decimal('0.00'),
                available_credits=credit_amount
            )
            db.add(user_credit)
            balance_after = credit_amount
        
        logger.info(f"Updated credits for referrer {referrer_user_id}: "
                   f"before={balance_before}, after={balance_after}")
        
        # 4. 记录交易历史
        transaction = CreditTransaction(
            user_id=referrer_user_id,
            transaction_type='earned',
            amount=credit_amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=f"Referral reward from user {referee_user_id}",
            reference_id=str(referral_record.id)
        )
        db.add(transaction)
        
        # 5. 更新推荐记录状态
        now = datetime.now(timezone.utc)
        stmt_update_record = (
            update(ReferralRecord)
            .where(ReferralRecord.id == referral_record.id)
            .values(
                status='completed',
                stripe_customer_id=stripe_customer_id,
                credited_at=now
            )
        )
        await db.execute(stmt_update_record)
        
        logger.info(f"Referral reward processed successfully: "
                   f"referrer={referrer_user_id}, amount={credit_amount}")
        
        return {
            "processed": True,
            "referrer_user_id": str(referrer_user_id),
            "referee_user_id": referee_user_id,
            "credit_amount": float(credit_amount),
            "new_balance": float(balance_after)
        }
        
    except Exception as e:
        logger.exception(f"Failed to process referral reward: {e}")
        raise