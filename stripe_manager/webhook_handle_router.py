from fastapi import APIRouter, Request, HTTPException
import httpx
import logging
import stripe
import json
from config import settings

SUPABASE_URL = settings.supabase_url
SUPABASE_KEY = settings.supabase_key
STRIPE_SECRET = settings.stripe_webhook_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe webhook handle manager(接收和处理 Stripe 的 webhook 事件，并同步用户订阅信息到 Supabase)"])

# 签名验证函数
def verify_stripe_signature(payload: bytes, header_signature: str) -> bool:
    """
    使用Stripe官方库验证签名 (推荐方式)
    """
    try:
        event = stripe.Webhook.construct_event(
            payload,
            header_signature,
            STRIPE_SECRET
        )
        return True
    except ValueError as e:
        logging.error(f"Invalid payload: {e}")
        return False
    except stripe.error.SignatureVerificationError as e:
        logging.error(f"Invalid signature: {e}")
        return False

async def update_user_subscription(email: str, level: str, stripe_customer_id: str):
    logging.info(f"Updating subscription for email={email} to level={level}")
    async with httpx.AsyncClient() as client:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        try:
            # 1. 更新 user_level 表
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/user_level?email=eq.{email}",
                headers=headers,
                json={"subscription_status": level, "stripe_customer_id": stripe_customer_id}
            )
            # 2. 更新 receipt_usage_quota_request 表
            request_limit = 100 if level == "pro" else 5
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/receipt_usage_quota_request?email=eq.{email}",
                headers=headers,
                json={"month_limit": request_limit}
            )
            # 3. 更新 receipt_usage_quota_receipt 表
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/receipt_usage_quota_receipt?email=eq.{email}",
                headers=headers,
                json={"month_limit": request_limit}
            )
            logging.info(f"Subscription update for email={email} completed.")
        except Exception as e:
            logging.error(f"Error updating subscription for email={email}: {e}")


@router.post("/webhook-handle")
async def stripe_webhook(request: Request):
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
        email = payload.get("data", {}).get("object",{}).get("customer_email")
        if not email:
            logging.warning("Missing email in data")
            raise HTTPException(status_code=400, detail="Missing email in data")
        logging.info(f"Received event_type={event_type} for email={email}")

        stripe_customer_id = payload.get("data", {}).get("object",{}).get("customer")
        # 更新 Supabase 状态
        if event_type == "invoice.payment_succeeded":
            await update_user_subscription(email, "pro", stripe_customer_id)
            logging.info(f"User {email} upgraded to pro.")
        elif event_type == "customer.subscription.deleted":
            await update_user_subscription(email, "free", stripe_customer_id)
            logging.info(f"User {email} downgraded to free.")
        else:
            logging.info(f"Unhandled event_type: {event_type}")
        logging.info(f"Webhook processing completed for email={email}")
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Error in webhook handler: {e}")
        raise
