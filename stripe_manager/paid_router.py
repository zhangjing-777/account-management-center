from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from core.utils import generate_email_hash
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe paid manager"])

@router.post("/paid-manager")
async def stripe_paid_process(request: dict, db: AsyncSession = Depends(get_db)):
    """处理 Stripe 支付成功回调，升级用户为 Pro 并增加配额"""
    try:
        subscription_id = (
            request.get("data", {})
            .get("object", {})
            .get("customer")
        )
        customer_email = (
            request.get("data", {})
            .get("object", {})
            .get("customer_email")
        )
        
        logger.info(f"Stripe webhook received: customer_email={customer_email}, stripe_id={subscription_id}")

        email_hash = generate_email_hash(customer_email)

        stmt1 = (
            update(UserLevelEn)
            .where(UserLevelEn.email_hash == email_hash)
            .values(subscription_status='Pro', stripe_customer_id=subscription_id)
        )
        result1 = await db.execute(stmt1)
        logger.info(f"user_level_en updated: {result1.rowcount} rows")

        stmt2 = (
            update(ReceiptUsageQuotaRequestEn)
            .where(ReceiptUsageQuotaRequestEn.email_hash == email_hash)
            .values(month_limit=100)
        )
        result2 = await db.execute(stmt2)
        logger.info(f"receipt_usage_quota_request_en updated: {result2.rowcount} rows")

        stmt3 = (
            update(ReceiptUsageQuotaReceiptEn)
            .where(ReceiptUsageQuotaReceiptEn.email_hash == email_hash)
            .values(month_limit=100)
        )
        result3 = await db.execute(stmt3)
        logger.info(f"receipt_usage_quota_receipt_en updated: {result3.rowcount} rows")

        await db.commit()
        logger.info("All updates committed successfully")

        return {
            "message": "Stripe payment processed, user upgraded to Pro",
            "customer_email": customer_email,
            "stripe_customer_id": subscription_id,
            "updates": {
                "user_level_en": result1,
                "receipt_usage_quota_request_en": result2,
                "receipt_usage_quota_receipt_en": result3
            },
            "status": "success"
        }

    except Exception as e:
        await db.rollback()
        logger.exception(f"Stripe paid process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

