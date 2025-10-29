from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from core.utils import generate_email_hash
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe paid manager"])


async def upgrade_user_to_pro(
    email_hash: str,
    stripe_customer_id: str,
    db: AsyncSession
) -> dict:
    """升级用户为 Pro 并增加配额"""
    stmt1 = (
        update(UserLevelEn)
        .where(UserLevelEn.email_hash == email_hash)
        .values(subscription_status='Pro', stripe_customer_id=stripe_customer_id)
    )
    result1 = await db.execute(stmt1)
    logger.info(f"user_level_en updated to Pro: {result1.rowcount} rows")

    stmt2 = (
        update(ReceiptUsageQuotaRequestEn)
        .where(ReceiptUsageQuotaRequestEn.email_hash == email_hash)
        .values(month_limit=100)
    )
    result2 = await db.execute(stmt2)
    logger.info(f"receipt_usage_quota_request_en updated to 100: {result2.rowcount} rows")

    stmt3 = (
        update(ReceiptUsageQuotaReceiptEn)
        .where(ReceiptUsageQuotaReceiptEn.email_hash == email_hash)
        .values(month_limit=100)
    )
    result3 = await db.execute(stmt3)
    logger.info(f"receipt_usage_quota_receipt_en updated to 100: {result3.rowcount} rows")

    return {
        "user_level_en": result1.rowcount,
        "receipt_usage_quota_request_en": result2.rowcount,
        "receipt_usage_quota_receipt_en": result3.rowcount
    }


async def downgrade_user_to_free(
    email_hash: str,
    db: AsyncSession
) -> dict:
    """降级用户为 Free 并减少配额"""
    stmt1 = (
        update(UserLevelEn)
        .where(UserLevelEn.email_hash == email_hash)
        .values(subscription_status='Free')
    )
    result1 = await db.execute(stmt1)
    logger.info(f"user_level_en updated to Free: {result1.rowcount} rows")

    stmt2 = (
        update(ReceiptUsageQuotaRequestEn)
        .where(ReceiptUsageQuotaRequestEn.email_hash == email_hash)
        .values(month_limit=0)
    )
    result2 = await db.execute(stmt2)
    logger.info(f"receipt_usage_quota_request_en updated to 5: {result2.rowcount} rows")

    stmt3 = (
        update(ReceiptUsageQuotaReceiptEn)
        .where(ReceiptUsageQuotaReceiptEn.email_hash == email_hash)
        .values(month_limit=0)
    )
    result3 = await db.execute(stmt3)
    logger.info(f"receipt_usage_quota_receipt_en updated to 5: {result3.rowcount} rows")

    return {
        "user_level_en": result1.rowcount,
        "receipt_usage_quota_request_en": result2.rowcount,
        "receipt_usage_quota_receipt_en": result3.rowcount
    }


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
            # 订阅成功或更新
            updates = await upgrade_user_to_pro(email_hash, stripe_customer_id, db)
            message = "User upgraded to Pro"
            status = "Pro"
            
        elif event_type == "customer.subscription.deleted":
            # 订阅取消
            updates = await downgrade_user_to_free(email_hash, db)
            message = "User downgraded to Free"
            status = "Free"
            
        else:
            logger.warning(f"Unhandled event type: {event_type}")
            return {
                "message": "Event type not handled",
                "event_type": event_type,
                "status": "ignored"
            }

        await db.commit()
        logger.info(f"All updates committed successfully for event: {event_type}")

        return {
            "message": message,
            "customer_email": customer_email,
            "stripe_customer_id": stripe_customer_id,
            "subscription_status": status,
            "updates": updates,
            "status": "success"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Stripe paid process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))