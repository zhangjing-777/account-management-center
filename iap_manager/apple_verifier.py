"""Apple JWS 验签（官方 app-store-server-library）

- 客户端上传的 StoreKit 2 交易（jwsRepresentation）
- App Store Server Notifications V2 的 signedPayload
都必须先验签再使用。旧代码只做 base64 解码，任何人都能伪造。

根证书下载（放进 settings.apple_root_cert_dir）：
  https://www.apple.com/certificateauthority/AppleRootCA-G3.cer
  https://www.apple.com/certificateauthority/AppleRootCA-G2.cer
  https://www.apple.com/certificateauthority/AppleIncRootCertificate.cer
"""
import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier, VerificationException

from core.config import settings

logger = logging.getLogger(__name__)


class AppleVerificationError(Exception):
    pass


@dataclass
class VerifiedTransaction:
    transaction_id: str
    original_transaction_id: str
    product_id: str
    bundle_id: str
    environment: str
    app_account_token: Optional[str]  # = Supabase user_id（小写），iOS 购买时传入
    purchased_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]


@dataclass
class VerifiedNotification:
    notification_type: str
    subtype: Optional[str]
    notification_uuid: Optional[str]
    signed_transaction_info: Optional[str]


# ---------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------
def _peek_jws(token: str) -> dict:
    """不验签地读出 payload，只用来决定用哪个 bundle/环境的 verifier"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception as e:
        raise AppleVerificationError(f"Malformed JWS: {e}")


@lru_cache(maxsize=1)
def _root_certificates() -> tuple[bytes, ...]:
    cert_dir = Path(settings.apple_root_cert_dir)
    certs = tuple(p.read_bytes() for p in sorted(cert_dir.glob("*.cer")))
    if not certs:
        raise RuntimeError(f"No Apple root certificates found in {cert_dir}")
    return certs


_verifiers: dict[tuple[str, str], SignedDataVerifier] = {}


def _verifier_for(bundle_id: Optional[str], environment: Optional[str]) -> SignedDataVerifier:
    if bundle_id not in settings.apple_bundle_id_list:
        raise AppleVerificationError(f"Unexpected bundle id: {bundle_id}")

    # 只接受 Apple 真实签名的环境。Xcode / LocalTesting 环境库会跳过验签，必须拒绝
    if environment == Environment.PRODUCTION.value:
        env = Environment.PRODUCTION
    elif environment == Environment.SANDBOX.value and settings.apple_allow_sandbox:
        env = Environment.SANDBOX
    else:
        raise AppleVerificationError(f"Environment not allowed: {environment}")

    key = (bundle_id, env.value)
    if key not in _verifiers:
        app_apple_id = settings.apple_app_apple_id_map.get(bundle_id)
        if env == Environment.PRODUCTION and not app_apple_id:
            raise RuntimeError(f"apple_app_apple_ids is missing an entry for {bundle_id}")
        _verifiers[key] = SignedDataVerifier(
            list(_root_certificates()), True, env, bundle_id, app_apple_id
        )
    return _verifiers[key]


def _ms_to_datetime(value) -> Optional[datetime]:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc) if value else None


# ---------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------
async def verify_transaction(signed_transaction: str) -> VerifiedTransaction:
    peek = _peek_jws(signed_transaction)
    verifier = _verifier_for(peek.get("bundleId"), peek.get("environment"))
    try:
        # 库是同步的，并且会做 OCSP 在线校验，放线程池里跑
        decoded = await asyncio.to_thread(verifier.verify_and_decode_signed_transaction, signed_transaction)
    except VerificationException as e:
        raise AppleVerificationError(f"Transaction verification failed: {e.status}")

    return VerifiedTransaction(
        transaction_id=str(decoded.transactionId),
        original_transaction_id=str(decoded.originalTransactionId),
        product_id=decoded.productId,
        bundle_id=decoded.bundleId,
        environment=decoded.rawEnvironment or peek.get("environment"),
        app_account_token=str(decoded.appAccountToken).lower() if decoded.appAccountToken else None,
        purchased_at=_ms_to_datetime(decoded.purchaseDate),
        expires_at=_ms_to_datetime(decoded.expiresDate),
        revoked_at=_ms_to_datetime(decoded.revocationDate),
    )


async def verify_notification(signed_payload: str) -> VerifiedNotification:
    peek = _peek_jws(signed_payload)
    data = peek.get("data") or {}
    verifier = _verifier_for(data.get("bundleId"), data.get("environment"))
    try:
        decoded = await asyncio.to_thread(verifier.verify_and_decode_notification, signed_payload)
    except VerificationException as e:
        raise AppleVerificationError(f"Notification verification failed: {e.status}")

    return VerifiedNotification(
        notification_type=decoded.rawNotificationType,
        subtype=decoded.rawSubtype,
        notification_uuid=decoded.notificationUUID,
        signed_transaction_info=decoded.data.signedTransactionInfo if decoded.data else None,
    )
