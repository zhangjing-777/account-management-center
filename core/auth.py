"""Supabase 登录校验：从 Authorization: Bearer <access_token> 取出当前 user_id

购买接口必须用这个，不能再让客户端在 body 里传 user_id
（旧的 /iap/verify-receipt 就是因为这个，谁都能给任意账号绑购买）
"""
import logging

import httpx
from fastapi import Header, HTTPException

from core.config import settings

logger = logging.getLogger(__name__)


async def current_user_id(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={"Authorization": authorization, "apikey": settings.supabase_key},
            )
    except httpx.HTTPError as e:
        logger.error(f"Supabase auth lookup failed: {e}")
        raise HTTPException(status_code=503, detail="Authentication is unavailable")

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="User is not authenticated")

    user_id = response.json().get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Authenticated user ID is missing")
    return user_id.lower()
