from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
import logging
import stripe
import json
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
from core.config import settings


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe webhook handle manager(接收和处理 Stripe 的 webhook 事件，并同步用户订阅信息)"])

def verify_stripe_signature(payload: bytes, header_signature: str) -> bool:
    try:
        event = stripe.Webhook.construct_event(
            payload,
            header_signature,
            settings.stripe_webhook_secret
        )
        return True
    except ValueError as e:
        logging.error(f"Invalid payload: {e}")
        return False
    except stripe.error.SignatureVerificationError as e:
        logging.error(f"Invalid signature: {e}")
        return False

async def update_user_subscription(db: AsyncSession, user_id: str, level: str, stripe_customer_id: str):
    logging.info(f"Updating subscription for user_id={user_id} to level={level}")
    
    try:
        # 1. 更新 user_level_en 表
        stmt1 = (
            update(UserLevelEn)
            .where(UserLevelEn.user_id == user_id)
            .values(subscription_status=level, stripe_customer_id=stripe_customer_id)
        )
        result1 = await db.execute(stmt1)
        logger.info(f"user_level_en updated: {result1.rowcount} rows")
        
        # 2. 更新 receipt_usage_quota_request_en 表
        request_limit = 100 if level == "pro" else 5
        stmt2 = (
            update(ReceiptUsageQuotaRequestEn)
            .where(ReceiptUsageQuotaRequestEn.user_id == user_id)
            .values(month_limit=request_limit)
        )
        result2 = await db.execute(stmt2)
        logger.info(f"receipt_usage_quota_request_en updated: {result2.rowcount} rows")
        
        # 3. 更新 receipt_usage_quota_receipt_en 表
        stmt3 = (
            update(ReceiptUsageQuotaReceiptEn)
            .where(ReceiptUsageQuotaReceiptEn.user_id == user_id)
            .values(month_limit=request_limit)
        )
        result3 = await db.execute(stmt3)
        logger.info(f"receipt_usage_quota_receipt_en updated: {result3.rowcount} rows")
        
        await db.commit()
        logging.info(f"Subscription update for user_id={user_id} completed.")
        
    except Exception as e:
        await db.rollback()
        logging.error(f"Error updating subscription for user_id={user_id}: {e}")
        raise

@router.post("/webhook-handle")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body)

        # Stripe 签名验证
        signature = request.headers.get("stripe-signature")
        if not signature:
            raise HTTPException(status_code=400, detail="Missing signature")
        if not verify_stripe_signature(raw_body, signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

        event_type = payload.get("type")
        
        # 从 metadata 中获取 user_id
        user_id = payload.get("data", {}).get("object", {}).get("metadata", {}).get("user_id")
        if not user_id:
            logging.warning("Missing user_id in metadata")
            raise HTTPException(status_code=400, detail="Missing user_id in metadata")
        
        logging.info(f"Received event_type={event_type} for user_id={user_id}")

        stripe_customer_id = payload.get("data", {}).get("object", {}).get("customer")
        
        # 更新数据库状态
        if event_type == "invoice.payment_succeeded":
            await update_user_subscription(db, user_id, "pro", stripe_customer_id)
            logging.info(f"User {user_id} upgraded to pro.")
        elif event_type == "customer.subscription.deleted":
            await update_user_subscription(db, user_id, "free", stripe_customer_id)
            logging.info(f"User {user_id} downgraded to free.")
        else:
            logging.info(f"Unhandled event_type: {event_type}")
        
        logging.info(f"Webhook processing completed for user_id={user_id}")
        return {"status": "success"}
        
    except Exception as e:
        logging.error(f"Error in webhook handler: {e}")
        raise
