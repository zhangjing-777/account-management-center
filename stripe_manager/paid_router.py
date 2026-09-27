from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from core.utils import generate_email_hash
from core.database import get_db

import stripe
from core.config import settings
from stripe_manager.annual_manager.code_service import generate_annual_code
from stripe_manager.credit_pack_manager.credit_service import fulfill_credit_pack

from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
from stripe_manager.referral_manager.reward_service import process_referral_reward
import logging

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_api_key  # 需要查line items,所以这个文件也要初始化一下

router = APIRouter(prefix="/stripe", tags=["stripe paid manager"])


async def update_user_subscription(db: AsyncSession, level: str, stripe_customer_id: str, email_hash: str = None):
    logging.info(f"Updating subscription for email_hash={email_hash} to level={level}")
    
    # 1. 更新 user_level_en 表
    query = UserLevelEn.email_hash == email_hash if email_hash else UserLevelEn.stripe_customer_id == stripe_customer_id
    stmt1 = (
        update(UserLevelEn)
        .where(query)
        .values(subscription_status=level, stripe_customer_id=stripe_customer_id)
        .returning(UserLevelEn.user_id)
    )

    result1 = await db.execute(stmt1)
    user_id = result1.scalar_one_or_none()
    logger.info(f"user_level_en updated: user_id={user_id}")

    # 根据订阅等级设置每月额度
    request_limit = {
        "pro": 100,
        "team": 1000,
    }.get(level, 0)

    # 2. 更新 receipt_usage_quota_request_en 表
    stmt2 = (
        update(ReceiptUsageQuotaRequestEn)
        .where(ReceiptUsageQuotaRequestEn.user_id == user_id)
        .values(month_limit=request_limit)
    )
    result2 = await db.execute(stmt2)
    logger.info(
        f"receipt_usage_quota_request_en updated: "
        f"user_id={user_id}, month_limit={request_limit}"
    )
    
    # 3. 更新 receipt_usage_quota_receipt_en 表
    stmt3 = (
        update(ReceiptUsageQuotaReceiptEn)
        .where(ReceiptUsageQuotaReceiptEn.user_id == user_id)
        .values(month_limit=request_limit)
    )
    result3 = await db.execute(stmt3)
    logger.info(
        f"receipt_usage_quota_receipt_en updated: "
        f"user_id={user_id}, month_limit={request_limit}"
    )

    await db.commit()
    logger.info(f"Subscription update for user_id={user_id} completed.")
    
    return user_id


@router.post("/paid-manager")
async def stripe_paid_process(request: dict, db: AsyncSession = Depends(get_db)):
    """处理 Stripe 支付回调（成功或取消订阅）"""
    try:
        logger.info(f"The input request is {request}")
        event_type = request.get("type", "")
        logger.info(f"The event_type is {event_type}")
        data_object = request.get("data", {}).get("object", {})       
        stripe_customer_id = data_object.get("customer")

        # 根据事件类型处理
        if event_type == "invoice.payment_succeeded":
            # 订阅成功
            customer_email = data_object.get("customer_email")
            if not customer_email:
                raise HTTPException(status_code=400, detail="customer_email is missing")
            email_hash = generate_email_hash(customer_email)

            description = (
                    data_object.get("lines", {})
                    .get("data", [{}])[0]
                    .get("description")
                    ).casefold()

            level = "team" if "team" in description else "pro" if "pro" in description else "free"
            logger.info(f"the paid level is {level}.")
            user_id = await update_user_subscription(db, level, stripe_customer_id, email_hash)
            message = f"User upgraded to {level}"
            status = level

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
            user_id = await update_user_subscription(db, "free", stripe_customer_id)
            message = "User downgraded to Free"
            status = "Free"

        elif event_type == "checkout.session.completed":
            # one-off支付（年度包 / 流量包）走这里，与订阅相关的 invoice.payment_succeeded 互不影响
            session_id = data_object.get("id")
            client_reference_id = data_object.get("client_reference_id")
            customer_email = (
                data_object.get("customer_details", {}).get("email")
                or data_object.get("customer_email")
            )

            # checkout.session.completed 默认不带 line items，需要单独查price_id
            line_items = stripe.checkout.Session.list_line_items(session_id, limit=1)
            price_id = line_items.data[0].price.id if line_items.data else None

            product_info = settings.stripe_price_map.get(price_id)
            if not product_info:
                logger.warning(f"Unknown price_id in checkout.session.completed: {price_id}")
                return {"message": "Unknown price_id", "status": "ignored"}

            if product_info["type"] == "annual":
                if not customer_email:
                    raise HTTPException(status_code=400, detail="customer email is missing")
                purchaser_email_hash = generate_email_hash(customer_email)
                code = await generate_annual_code(
                    db, session_id, product_info["plan"], purchaser_email_hash, client_reference_id
                )
                return {
                    "message": "Annual code generated",
                    "plan": product_info["plan"],
                    "code": code,
                    "status": "success",
                }

            elif product_info["type"] == "credit_pack":
                if not client_reference_id:
                    logger.error(f"Credit pack purchase without client_reference_id, session={session_id}")
                    return {"message": "Missing client_reference_id, cannot fulfill credit pack", "status": "error"}
                await fulfill_credit_pack(db, session_id, client_reference_id, product_info["credits"])
                return {"message": "Credit pack fulfilled", "status": "success"}
               
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