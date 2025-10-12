from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe paid manager"])

class StripeWebhookBody(BaseModel):
    user_id: str
    id: str

@router.post("/paid-manager")
async def stripe_paid_process(body: StripeWebhookBody, db: AsyncSession = Depends(get_db)):
    """处理 Stripe 支付成功回调，升级用户为 Pro 并增加配额"""
    try:
        logger.info(f"Stripe webhook received: user_id={body.user_id}, stripe_id={body.id}")

        stmt1 = (
            update(UserLevelEn)
            .where(UserLevelEn.user_id == body.user_id)
            .values(subscription_status='Pro', stripe_customer_id=body.id)
        )
        result1 = await db.execute(stmt1)
        logger.info(f"user_level_en updated: {result1.rowcount} rows")

        stmt2 = (
            update(ReceiptUsageQuotaRequestEn)
            .where(ReceiptUsageQuotaRequestEn.user_id == body.user_id)
            .values(month_limit=100)
        )
        result2 = await db.execute(stmt2)
        logger.info(f"receipt_usage_quota_request_en updated: {result2.rowcount} rows")

        stmt3 = (
            update(ReceiptUsageQuotaReceiptEn)
            .where(ReceiptUsageQuotaReceiptEn.user_id == body.user_id)
            .values(month_limit=100)
        )
        result3 = await db.execute(stmt3)
        logger.info(f"receipt_usage_quota_receipt_en updated: {result3.rowcount} rows")

        await db.commit()
        logger.info("All updates committed successfully")

        return {
            "message": "Stripe payment processed, user upgraded to Pro",
            "user_id": body.user_id,
            "stripe_customer_id": body.id,
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

