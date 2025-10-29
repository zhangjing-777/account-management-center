from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from core.utils import generate_email_hash
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
from stripe_manager.referral_manager.reward_service import process_referral_reward
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe paid manager"])


async def update_user_subscription(db: AsyncSession, email_hash: str, level: str, stripe_customer_id: str):
    logging.info(f"Updating subscription for email_hash={email_hash} to level={level}")
    
    # 1. 更新 user_level_en 表
    stmt1 = (
        update(UserLevelEn)
        .where(UserLevelEn.email_hash == email_hash)
        .values(subscription_status=level, stripe_customer_id=stripe_customer_id)
        .returning(UserLevelEn.user_id)
    )
    result1 = await db.execute(stmt1)
    user_id = result1.scalar_one_or_none()
    logger.info(f"user_level_en updated: {result1.rowcount} rows, user_id={user_id}")
    
    # 2. 更新 receipt_usage_quota_request_en 表
    request_limit = 100 if level == "pro" else 0
    stmt2 = (
        update(ReceiptUsageQuotaRequestEn)
        .where(ReceiptUsageQuotaRequestEn.email_hash == email_hash)
        .values(month_limit=request_limit)
    )
    result2 = await db.execute(stmt2)
    logger.info(f"receipt_usage_quota_request_en updated: {result2.rowcount} rows")
    
    # 3. 更新 receipt_usage_quota_receipt_en 表
    stmt3 = (
        update(ReceiptUsageQuotaReceiptEn)
        .where(ReceiptUsageQuotaReceiptEn.email_hash == email_hash)
        .values(month_limit=request_limit)
    )
    result3 = await db.execute(stmt3)
    logger.info(f"receipt_usage_quota_receipt_en updated: {result3.rowcount} rows")

    await db.commit()
    logger.info(f"Subscription update for email_hash={email_hash} completed.")
    
    return user_id


@router.post("/paid-manager")
async def stripe_paid_process(request: dict, db: AsyncSession = Depends(get_db)):
    """处理 Stripe 支付回调（成功或取消订阅）"""
    try:
        logger.info(f"The input request is {request}")
        event_type = request.get("type", "")
        data_object = request.get("data", {}).get("object", {})
        
        customer_email = data_object.get("customer_email")
        stripe_customer_id = data_object.get("customer")
        
        if not customer_email:
            raise HTTPException(status_code=400, detail="customer_email is missing")
        
        logger.info(f"Stripe webhook received: type={event_type}, email={customer_email}, stripe_id={stripe_customer_id}")

        email_hash = generate_email_hash(customer_email)

        # 根据事件类型处理
        if event_type == "invoice.payment_succeeded":
            # 订阅成功
            user_id = await update_user_subscription(db, email_hash, "pro", stripe_customer_id)
            message = "User upgraded to Pro"
            status = "Pro"

            # 触发推荐返利
            try:
                reward_result = await process_referral_reward(
                    db=db,
                    referee_user_id=user_id,
                    stripe_customer_id=stripe_customer_id
                )
                
                if reward_result.get("processed"):
                    logger.info(f"Referral reward processed: {reward_result}")
                else:
                    logger.info(f"Referral reward not processed: {reward_result.get('reason')}")
                    
            except Exception as e:
                logger.error(f"Failed to process referral reward: {e}")
                # 不阻断主流程，继续执行
                
        elif event_type == "customer.subscription.deleted":
            # 订阅取消
            user_id = await update_user_subscription(db, email_hash, "free", stripe_customer_id)
            message = "User downgraded to Free"
            status = "Free"
            
        else:
            logger.warning(f"Unhandled event type: {event_type}")
            return {
                "message": "Event type not handled",
                "event_type": event_type,
                "status": "ignored"
            }

        logger.info(f"All updates committed successfully for event: {event_type}")

        return {
            "message": message,
            "customer_email": customer_email,
            "stripe_customer_id": stripe_customer_id,
            "subscription_status": status,
            "updates": user_id,
            "status": "success"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Stripe paid process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))