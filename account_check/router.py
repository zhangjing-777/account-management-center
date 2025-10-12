from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["检查用户的账户状态"])

class AccountCheckRequest(BaseModel):
    user_id: str

@router.post("/account-check")
async def account_check(request: AccountCheckRequest, db: AsyncSession = Depends(get_db)):
    try:
        stmt = (
            select(
                UserLevelEn.user_id,
                UserLevelEn.subscription_status,
                UserLevelEn.virtual_box,
                func.coalesce(ReceiptUsageQuotaReceiptEn.used_month, 0).label("usage_quota_receipt"),
                func.coalesce(ReceiptUsageQuotaRequestEn.used_month, 0).label("usage_quota_request"),
                func.coalesce(ReceiptUsageQuotaReceiptEn.month_limit, 0).label("receipt_month_limit"),
                func.coalesce(ReceiptUsageQuotaRequestEn.month_limit, 0).label("request_month_limit")
            )
            .outerjoin(ReceiptUsageQuotaReceiptEn, UserLevelEn.user_id == ReceiptUsageQuotaReceiptEn.user_id)
            .outerjoin(ReceiptUsageQuotaRequestEn, UserLevelEn.user_id == ReceiptUsageQuotaRequestEn.user_id)
            .where(UserLevelEn.user_id == request.user_id)
        )
        
        result = await db.execute(stmt)
        record = result.first()

        if not record:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "user_id": record.user_id,
            "subscription_status": record.subscription_status,
            "virtual_box": record.virtual_box,
            "receipt_quota": {
                "used": record.usage_quota_receipt,
                "limit": record.receipt_month_limit,
                "remaining": max(0, record.receipt_month_limit - record.usage_quota_receipt),
                "utilization_percentage": round(record.usage_quota_receipt / record.receipt_month_limit, 2) if record.receipt_month_limit > 0 else 0
            },
            "request_quota": {
                "used": record.usage_quota_request,
                "limit": record.request_month_limit,
                "remaining": max(0, record.request_month_limit - record.usage_quota_request),
                "utilization_percentage": round(record.usage_quota_request / record.request_month_limit, 2) if record.request_month_limit > 0 else 0
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Account check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

