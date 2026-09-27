from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from core.database import get_db
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["检查用户的账户状态"])

# 新用户注册赠送的永久额度（auth_new_user/services.py 里写入 raw_limit=50）
SIGNUP_RAW_GRANT = 50


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
                func.coalesce(ReceiptUsageQuotaReceiptEn.used_month, 0).label("month_used"),
                func.coalesce(ReceiptUsageQuotaReceiptEn.month_limit, 0).label("month_limit"),
                func.coalesce(ReceiptUsageQuotaReceiptEn.raw_limit, 0).label("raw_left"),
            )
            .outerjoin(ReceiptUsageQuotaReceiptEn, UserLevelEn.user_id == ReceiptUsageQuotaReceiptEn.user_id)
            .where(UserLevelEn.user_id == request.user_id)
        )

        record = (await db.execute(stmt)).first()
        if not record:
            raise HTTPException(status_code=404, detail="User not found")

        # raw_limit 字段在库里存的是“永久池剩余量”（注册送的 + 买的包，用一张减一张）
        raw_left = max(record.raw_left, 0)
        month_remaining = max(record.month_limit - record.month_used, 0)

        # 兼容老版本 App：老 App 用 raw_limit - raw_used 算剩余
        # 这样算保证 raw_used 不为负，且 raw_limit - raw_used 恰好等于真实剩余
        legacy_raw_used = max(SIGNUP_RAW_GRANT - raw_left, 0)
        legacy_raw_limit = legacy_raw_used + raw_left

        return {
            "user_id": record.user_id,
            "subscription_status": record.subscription_status,
            "virtual_box": record.virtual_box,
            "receipt_quota": {
                "month_used": record.month_used,
                "month_limit": record.month_limit,
                "raw_used": legacy_raw_used,
                "raw_limit": legacy_raw_limit,
                # 新字段，新版前端用这几个
                "month_remaining": month_remaining,
                "pack_remaining": raw_left,
                "total_remaining": month_remaining + raw_left,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Account check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))