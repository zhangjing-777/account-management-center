"""App Store Server Notifications V2（续费 / 过期 / 退款 / 一次性购买）

POST /iap/v2/notification
在 App Store Connect 里把 ReceiptDrop 和 ReceiptTalk 两个 App 的
Production + Sandbox Server URL 都填成：
  https://account-management-center.receiptdrop.dev/iap/v2/notification

返回码约定：
  200 已处理 / 可以忽略（Apple 不再重试）
  400 验签失败（伪造的请求）
  500 我们自己出错（Apple 会自动重试，最多 5 次）
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from iap_manager.apple_verifier import (
    AppleVerificationError,
    verify_notification,
    verify_transaction,
)
from iap_manager.fulfillment_service import (
    UnknownProductError,
    fulfill_transaction,
    resolve_user_id,
    revoke_transaction,
    unrevoke_transaction,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iap/v2", tags=["Apple IAP v2 notifications"])

REVOKE_TYPES = {"REFUND", "REVOKE"}


class AppleNotificationPayload(BaseModel):
    signedPayload: str


@router.post("/notification")
async def apple_notification_v2(payload: AppleNotificationPayload, db: AsyncSession = Depends(get_db)):
    try:
        notification = await verify_notification(payload.signedPayload)
    except AppleVerificationError as e:
        logger.warning(f"[IAP notify] rejected: {e}")
        raise HTTPException(status_code=400, detail="Invalid notification")

    ntype, subtype = notification.notification_type, notification.subtype
    logger.info(f"[IAP notify] type={ntype} subtype={subtype} uuid={notification.notification_uuid}")

    if ntype == "TEST" or not notification.signed_transaction_info:
        return {"status": "ok", "handled": False}

    try:
        tx = await verify_transaction(notification.signed_transaction_info)
    except AppleVerificationError as e:
        logger.warning(f"[IAP notify] transaction rejected: {e}")
        raise HTTPException(status_code=400, detail="Invalid transaction")

    user_id = await resolve_user_id(db, tx)
    if not user_id:
        # 没有 appAccountToken 的老交易，且 App 还没上报过；等 App 调 /iap/v2/transaction 时会补上
        logger.warning(f"[IAP notify] no user for original_tx={tx.original_transaction_id}")
        return {"status": "ok", "handled": False, "reason": "user_not_found"}

    try:
        if ntype in REVOKE_TYPES:
            result = await revoke_transaction(db, tx, user_id)
        elif ntype == "REFUND_REVERSED":
            result = await unrevoke_transaction(db, tx, user_id)
        else:
            # SUBSCRIBED / DID_RENEW / ONE_TIME_CHARGE / EXPIRED / DID_FAIL_TO_RENEW /
            # GRACE_PERIOD_EXPIRED / DID_CHANGE_RENEWAL_STATUS ...
            # 统一：记录交易（幂等）+ 按流水重算订阅状态。过期的会自动降级
            result = await fulfill_transaction(db, tx, user_id)
    except UnknownProductError as e:
        logger.warning(f"[IAP notify] {e}")
        return {"status": "ok", "handled": False, "reason": "unknown_product"}
    except Exception as e:
        await db.rollback()
        logger.exception(f"[IAP notify] failed type={ntype} tx={tx.transaction_id}: {e}")
        raise HTTPException(status_code=500, detail="Notification processing failed")

    return {"status": "ok", "handled": True, "type": ntype, "user_id": user_id, **result}
