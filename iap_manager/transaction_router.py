"""iOS 购买完成后调用：上传 StoreKit 2 的 jwsRepresentation → 验签 → 入账

POST /iap/v2/transaction
Header: Authorization: Bearer <Supabase access_token>
Body:   {"signed_transaction": "<Transaction jwsRepresentation>"}

购买、恢复购买、App 启动时补发未完成交易，都走这一个接口（幂等）
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import current_user_id
from core.database import get_db
from core.models import AivoiceBalance, ReceiptUsageQuotaReceiptEn, UserLevelEn
from iap_manager.apple_verifier import AppleVerificationError, verify_transaction
from iap_manager.fulfillment_service import (
    UnknownProductError,
    fulfill_transaction,
    resolve_user_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iap/v2", tags=["Apple IAP v2 (StoreKit 2)"])


class SignedTransactionRequest(BaseModel):
    signed_transaction: str


@router.post("/transaction")
async def submit_transaction(
    request: SignedTransactionRequest,
    user_id: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        tx = await verify_transaction(request.signed_transaction)
    except AppleVerificationError as e:
        logger.warning(f"[IAP v2] verification failed user={user_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # 防止 A 账号的购买被 B 账号领走
    if tx.app_account_token and tx.app_account_token != user_id:
        raise HTTPException(status_code=409, detail="This purchase belongs to another account")
    owner = await resolve_user_id(db, tx)
    if owner and owner != user_id:
        raise HTTPException(status_code=409, detail="This purchase is already linked to another account")

    try:
        result = await fulfill_transaction(db, tx, user_id)
    except UnknownProductError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.exception(f"[IAP v2] fulfill failed tx={tx.transaction_id}: {e}")
        raise HTTPException(status_code=500, detail="Purchase could not be applied, please retry")

    return {
        "status": "success",
        "transaction_id": tx.transaction_id,
        "product_id": tx.product_id,
        **result,
        "entitlements": await _entitlements(db, user_id),
    }


async def _entitlements(db: AsyncSession, user_id: str) -> dict:
    """返回最新额度，App 购买成功后直接刷新 UI"""
    row = (await db.execute(
        select(
            UserLevelEn.subscription_status,
            ReceiptUsageQuotaReceiptEn.month_limit,
            ReceiptUsageQuotaReceiptEn.used_month,
            ReceiptUsageQuotaReceiptEn.raw_limit,
            AivoiceBalance.pack_seconds,
        )
        .outerjoin(ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaReceiptEn.user_id == UserLevelEn.user_id)
        .outerjoin(AivoiceBalance, AivoiceBalance.user_id == UserLevelEn.user_id)
        .where(UserLevelEn.user_id == user_id)
    )).first()
    if not row:
        return {}
    return {
        "subscription_status": row.subscription_status,
        "receipt_month_limit": row.month_limit or 0,
        "receipt_month_used": row.used_month or 0,
        "receipt_pack_remaining": row.raw_limit or 0,
        "voice_pack_seconds": row.pack_seconds or 0,
    }
