from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncpg
import logging
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe paid manager"])


class StripeWebhookBody(BaseModel):
    user_id: str
    id: str   # Stripe customer id


@router.post("/paid-manager")
async def stripe_paid_process(body: StripeWebhookBody):
    """处理 Stripe 支付成功回调，升级用户为 Pro 并增加配额"""
    try:
        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)
        logger.info(f"Stripe webhook received: user_id={body.user_id}, stripe_id={body.id}")

        # 1. 更新 user_level_en
        result1 = await conn.execute("""
            UPDATE public.user_level_en
            SET subscription_status = 'Pro',
                stripe_customer_id = $1
            WHERE user_id = $2
        """, body.id, body.user_id)
        logger.info(f"user_level_en updated: {result1}")

        # 2. 更新 receipt_usage_quota_request_en
        result2 = await conn.execute("""
            UPDATE public.receipt_usage_quota_request_en
            SET month_limit = 100
            WHERE user_id = $1
        """, body.user_id)
        logger.info(f"receipt_usage_quota_request_en updated: {result2}")

        # 3. 更新 receipt_usage_quota_receipt_en
        result3 = await conn.execute("""
            UPDATE public.receipt_usage_quota_receipt_en
            SET month_limit = 100
            WHERE user_id = $1
        """, body.user_id)
        logger.info(f"receipt_usage_quota_receipt_en updated: {result3}")

        await conn.close()
        logger.info("Database connection closed")

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
        logger.exception(f"Stripe paid process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
