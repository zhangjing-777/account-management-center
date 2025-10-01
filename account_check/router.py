from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncpg
from config import settings


router = APIRouter(prefix="/users", tags=["检查用户的账户状态"])

class AccountCheckRequest(BaseModel):
    user_id: str

@router.post("/account-check")
async def account_check(request: AccountCheckRequest):
    try:
        conn = await asyncpg.connect(dsn=settings.database_url, statement_cache_size=0)
        query = """
        SELECT
          ul.user_id,
          ul.subscription_status,
          ul.virtual_box,
          COALESCE(rur.used_month, 0) AS usage_quota_receipt,
          COALESCE(ruq.used_month, 0) AS usage_quota_request,
          COALESCE(rur.month_limit, 0) AS receipt_month_limit,
          COALESCE(ruq.month_limit, 0) AS request_month_limit
        FROM user_level ul
        LEFT JOIN receipt_usage_quota_receipt rur ON ul.user_id = rur.user_id
        LEFT JOIN receipt_usage_quota_request ruq ON ul.user_id = ruq.user_id
        WHERE ul.user_id = $1;
        """
        record = await conn.fetchrow(query, request.user_id)
        await conn.close()

        if not record:
            raise HTTPException(status_code=404, detail="User not found")

        result = {
            "user_id": record["user_id"],
            "subscription_status": record["subscription_status"],
            "virtual_box": record["virtual_box"],
            "receipt_quota": {
                    "used": record["usage_quota_receipt"],
                    "limit": record["receipt_month_limit"],
                    "remaining": max(0, record["receipt_month_limit"] - record["usage_quota_receipt"]),
                    "utilization_percentage": round(record["usage_quota_receipt"]/record["receipt_month_limit"], 2)
                },
            "request_quota": {
                    "used": record["usage_quota_request"],
                    "limit": record["request_month_limit"],
                    "remaining": max(0, record["request_month_limit"] - record["usage_quota_request"]),
                    "utilization_percentage": round(record["usage_quota_request"]/record["request_month_limit"], 2)
                }           
        }

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
