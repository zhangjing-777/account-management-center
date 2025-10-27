"""验证收据 + 绑定用户"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
from core.config import settings
import logging
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iap", tags=["Apple IAP verify-receipt"])


class VerifyReceiptRequest(BaseModel):
    user_id: str
    receipt: str  # Base64 encoded receipt data


@router.post("/verify-receipt")
async def verify_receipt(
    request: VerifyReceiptRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    验证 Apple IAP 收据，绑定 user_id ↔ original_transaction_id
    
    支持场景：
    1. 首次购买 - 建立绑定
    2. 恢复购买 - 自动找回绑定
    3. 续费校验 - 验证当前状态
    """
    try:
        # Step 1: 向 Apple 验证收据
        apple_response = await verify_with_apple(request.receipt)
        
        if apple_response.get("status") != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Apple receipt verification failed: {apple_response.get('status')}"
            )
        
        # Step 2: 提取 original_transaction_id
        latest_receipt_info = apple_response.get("latest_receipt_info", [])
        if not latest_receipt_info:
            raise HTTPException(status_code=400, detail="No valid transaction found")
        
        # 获取最新的交易信息
        latest_transaction = latest_receipt_info[-1]
        original_transaction_id = latest_transaction.get("original_transaction_id")
        
        if not original_transaction_id:
            raise HTTPException(status_code=400, detail="Missing original_transaction_id")
        
        logger.info(f"IAP verification: user_id={request.user_id}, "
                   f"original_transaction_id={original_transaction_id}")
        
        # Step 3: 检查是否已存在绑定
        stmt = select(UserLevelEn).where(
            UserLevelEn.apple_customer_id == original_transaction_id
        )
        result = await db.execute(stmt)
        existing_user = result.scalar_one_or_none()
        
        if existing_user and existing_user.user_id != request.user_id:
            # 该 original_transaction_id 已绑定其他用户
            raise HTTPException(
                status_code=409,
                detail="This purchase is already linked to another account"
            )
        
        # Step 4: 更新或创建绑定
        stmt_update = (
            update(UserLevelEn)
            .where(UserLevelEn.user_id == request.user_id)
            .values(
                apple_customer_id=original_transaction_id,
                subscription_status='Pro'
            )
        )
        result1 = await db.execute(stmt_update)
        logger.info(f"user_level_en updated: {result1.rowcount} rows")
        
        # Step 5: 升级配额（与 Stripe 保持一致）
        stmt2 = (
            update(ReceiptUsageQuotaRequestEn)
            .where(ReceiptUsageQuotaRequestEn.user_id == request.user_id)
            .values(month_limit=100)
        )
        result2 = await db.execute(stmt2)
        logger.info(f"receipt_usage_quota_request_en updated: {result2.rowcount} rows")
        
        stmt3 = (
            update(ReceiptUsageQuotaReceiptEn)
            .where(ReceiptUsageQuotaReceiptEn.user_id == request.user_id)
            .values(month_limit=100)
        )
        result3 = await db.execute(stmt3)
        logger.info(f"receipt_usage_quota_receipt_en updated: {result3.rowcount} rows")
        
        await db.commit()
        logger.info("IAP verification completed successfully")
        
        return {
            "message": "Receipt verified and user upgraded to Pro",
            "user_id": request.user_id,
            "apple_customer_id": original_transaction_id,
            "subscription_status": "Pro",
            "updates": {
                "user_level_en": result1.rowcount,
                "receipt_usage_quota_request_en": result2.rowcount,
                "receipt_usage_quota_receipt_en": result3.rowcount
            },
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"IAP verify receipt failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def verify_with_apple(receipt_data: str) -> dict:
    """
    向 Apple 服务器验证收据
    
    先尝试生产环境，如果返回 21007 则尝试沙盒环境
    """
    production_url = "https://buy.itunes.apple.com/verifyReceipt"
    sandbox_url = "https://sandbox.itunes.apple.com/verifyReceipt"
    
    payload = {
        "receipt-data": receipt_data,
        "password": settings.apple_shared_secret,  # 需要在 config 中配置
        "exclude-old-transactions": True
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 先尝试生产环境
        response = await client.post(production_url, json=payload)
        result = response.json()
        
        # 如果是沙盒收据（status=21007），切换到沙盒环境
        if result.get("status") == 21007:
            logger.info("Receipt is from sandbox, retrying with sandbox URL")
            response = await client.post(sandbox_url, json=payload)
            result = response.json()
        
        return result