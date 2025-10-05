from fastapi import APIRouter, HTTPException
from supabase import create_client, Client
from pydantic import BaseModel, EmailStr
import stripe
import logging
from config import settings


stripe.api_key = settings.stripe_api_key
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_key
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe subscript manager"])

class EmailRequest(BaseModel):
    email: EmailStr

@router.post("/subscript-manager")
async def create_customer_portal(request: EmailRequest):
    """
    创建Stripe Customer Portal会话, 返回portal链接
    
    请求: {"email": "user@example.com"}
    返回: portal链接字符串
    """
    try:
        # 从Supabase查询stripe_customer_id
        result = supabase.table("user_level_en").select("stripe_customer_id").eq("email", request.email).execute()
        
        if not result.data or not result.data[0].get("stripe_customer_id"):
            raise HTTPException(status_code=404, detail="Customer not found")
        
        customer_id = result.data[0]["stripe_customer_id"]
        
        # 创建Stripe Customer Portal会话
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url="https://receiptdrop.dev/dashboard"
        )
        
        logging.info(f"Portal session created: {portal_session}")
        # 直接返回URL字符串
        logging.info(f"Portal session url: {portal_session.url}")
        return portal_session.url
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))