"""Apple Webhook 自动续订"""
from typing import Optional
import base64
import logging
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import APIRouter, HTTPException, Depends
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iap", tags=["Apple IAP DID Renew"])


class AppleNotificationPayload(BaseModel):
    signedPayload: str  # Apple 的 JWS 格式数据


@router.post("/notification")
async def apple_webhook(
    payload: AppleNotificationPayload,
    db: AsyncSession = Depends(get_db)
):
    """
    处理 Apple App Store Server Notifications (版本 2)
    
    自动续订场景：
    - DID_RENEW: 订阅成功续期
    - DID_CHANGE_RENEWAL_STATUS: 续订状态变更
    - EXPIRED: 订阅过期
    - REFUND: 退款
    """
    try:
        # Step 1: 解码 Apple 的 JWS (JSON Web Signature)
        decoded_payload = decode_apple_jws(payload.signedPayload)
        
        notification_type = decoded_payload.get("notificationType")
        subtype = decoded_payload.get("subtype")
        
        logger.info(f"Apple webhook received: type={notification_type}, subtype={subtype}")
        
        # Step 2: 提取交易信息
        data = decoded_payload.get("data", {})
        signed_transaction_info = data.get("signedTransactionInfo")
        
        if not signed_transaction_info:
            raise HTTPException(status_code=400, detail="Missing transaction info")
        
        # 解码交易信息
        transaction = decode_apple_jws(signed_transaction_info)
        original_transaction_id = transaction.get("originalTransactionId")
        
        if not original_transaction_id:
            raise HTTPException(status_code=400, detail="Missing originalTransactionId")
        
        logger.info(f"Processing transaction: original_transaction_id={original_transaction_id}")
        
        # Step 3: 根据通知类型确定订阅状态
        new_status = determine_subscription_status(notification_type, subtype)
        
        # Step 4: 通过 apple_customer_id 查找用户
        stmt = select(UserLevelEn).where(
            UserLevelEn.apple_customer_id == original_transaction_id
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            logger.warning(f"No user found for original_transaction_id={original_transaction_id}")
            return {"status": "ignored", "reason": "user_not_found"}
        
        logger.info(f"Found user: user_id={user.user_id}, current_status={user.subscription_status}")
        
        # Step 5: 更新用户订阅状态
        stmt_update = (
            update(UserLevelEn)
            .where(UserLevelEn.apple_customer_id == original_transaction_id)
            .values(subscription_status=new_status)
        )
        result1 = await db.execute(stmt_update)
        logger.info(f"user_level_en updated: {result1.rowcount} rows")
        
        # Step 6: 根据状态调整配额
        if new_status == "Pro":
            # 续订成功，确保配额为 100
            stmt2 = (
                update(ReceiptUsageQuotaRequestEn)
                .where(ReceiptUsageQuotaRequestEn.user_id == user.user_id)
                .values(month_limit=100)
            )
            result2 = await db.execute(stmt2)
            logger.info(f"receipt_usage_quota_request_en updated: {result2.rowcount} rows")
            
            stmt3 = (
                update(ReceiptUsageQuotaReceiptEn)
                .where(ReceiptUsageQuotaReceiptEn.user_id == user.user_id)
                .values(month_limit=100)
            )
            result3 = await db.execute(stmt3)
            logger.info(f"receipt_usage_quota_receipt_en updated: {result3.rowcount} rows")
            
            logger.info(f"Quota upgraded for user_id={user.user_id}")
            
        elif new_status in ["Expired", "Cancelled"]:
            # 订阅失效，可以选择降级配额（根据需求决定）
            # 这里暂时不处理，保持原配额
            logger.info(f"Subscription {new_status} for user_id={user.user_id}")
        
        await db.commit()
        logger.info(f"Apple webhook processed successfully for user_id={user.user_id}")
        
        return {
            "message": "Apple notification processed",
            "user_id": user.user_id,
            "notification_type": notification_type,
            "new_status": new_status,
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Apple webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def decode_apple_jws(jws_token: str) -> dict:
    """
    解码 Apple 的 JWS (JSON Web Signature)
    
    注意: 生产环境中应验证签名，这里简化处理
    """
    try:
        # JWS 格式: header.payload.signature
        parts = jws_token.split('.')
        if len(parts) != 3:
            raise ValueError("Invalid JWS format")
        
        # 解码 payload (Base64 URL safe)
        payload = parts[1]
        # 添加必要的 padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded_bytes = base64.urlsafe_b64decode(payload)
        decoded_json = decoded_bytes.decode('utf-8')
        
        import json
        return json.loads(decoded_json)
        
    except Exception as e:
        logger.exception(f"Failed to decode JWS: {e}")
        raise HTTPException(status_code=400, detail="Invalid JWS token")


def determine_subscription_status(notification_type: str, subtype: Optional[str]) -> str:
    """
    根据 Apple 通知类型确定订阅状态
    
    Apple Notification Types (v2):
    - DID_RENEW: 自动续订成功
    - EXPIRED: 订阅过期
    - DID_CHANGE_RENEWAL_STATUS: 用户开启/关闭自动续订
    - REFUND: 退款
    - SUBSCRIBED: 新订阅或重新订阅
    """
    if notification_type in ["DID_RENEW", "SUBSCRIBED"]:
        return "Pro"
    elif notification_type == "EXPIRED":
        return "Expired"
    elif notification_type == "REFUND":
        return "Refunded"
    elif notification_type == "DID_CHANGE_RENEWAL_STATUS":
        # 如果用户取消了自动续订，但订阅仍在有效期内，保持 Pro
        # 等到真正过期时会收到 EXPIRED 通知
        return "Pro"
    else:
        # 其他类型暂时保持原状态
        logger.warning(f"Unknown notification type: {notification_type}")
        return "Pro"