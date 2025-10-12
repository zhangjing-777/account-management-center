from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe
import logging
from core.database import get_db
from core.models import UserLevelEn
from core.config import settings

stripe.api_key = settings.stripe_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe subscript manager"])


@router.post("/subscript-manager")
async def create_customer_portal(user_id: str, db: AsyncSession = Depends(get_db)):
    """
    创建Stripe Customer Portal会话, 返回portal链接
    
    请求: {"user_id": "uuid-string"}
    返回: portal链接字符串
    """
    try:
        # 通过 user_id 查询 stripe_customer_id
        stmt = select(UserLevelEn.stripe_customer_id).where(UserLevelEn.user_id == user_id)
        result = await db.execute(stmt)
        stripe_customer_id = result.scalar_one_or_none()
        
        if not stripe_customer_id:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        # 创建Stripe Customer Portal会话
        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url="https://receiptdrop.dev/dashboard"
        )
        
        logger.info(f"Portal session created for user_id={user_id}")
        logger.info(f"Portal session url: {portal_session.url}")
        
        return portal_session.url
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to create portal session: {e}")
        raise HTTPException(status_code=500, detail=str(e))