from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import stripe
import logging
from core.database import get_db
from core.models import UserLevelEn
from core.config import settings

stripe.api_key = settings.stripe_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe subscript manager"])


class CustomerPortalRequest(BaseModel):
    """客户门户请求模型"""
    user_id: str


@router.post("/subscript-manager")
async def create_customer_portal(
    request: CustomerPortalRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    创建Stripe Customer Portal会话, 返回portal链接
    
    请求: {"user_id": "uuid-string"}
    返回: portal链接字符串
    """
    try:
        user_id = request.user_id
        logger.info(f"Creating portal session for user_id: {user_id}")
        
        # 通过 user_id 查询 stripe_customer_id
        stmt = select(UserLevelEn.stripe_customer_id).where(UserLevelEn.user_id == user_id)
        result = await db.execute(stmt)
        stripe_customer_id = result.scalar_one_or_none()
        
        if not stripe_customer_id:
            logger.warning(f"No Stripe customer found for user_id: {user_id}")
            raise HTTPException(
                status_code=404,
                detail="Customer not found or has not subscribed yet"
            )
        
        logger.info(f"Found stripe_customer_id: {stripe_customer_id}")
        
        # 创建Stripe Customer Portal会话
        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url="https://receiptdrop.dev/dashboard"
        )
        
        logger.info(f"Portal session created successfully: {portal_session.url}")
        
        return portal_session.url
        
    except HTTPException:
        raise
    except stripe.error.StripeError as e:
        logger.exception(f"Stripe error when creating portal session: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Stripe error: {str(e)}"
        )
    except Exception as e:
        logger.exception(f"Failed to create portal session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

