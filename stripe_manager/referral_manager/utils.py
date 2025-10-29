import random
import string
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.models import ReferralCode
import logging

logger = logging.getLogger(__name__)


def generate_referral_code(length: int = 6) -> str:
    """生成随机邀请码（字母数字组合，大写）"""
    characters = string.ascii_uppercase + string.digits
    # 避免混淆的字符：0/O, 1/I/L
    characters = characters.replace('O', '').replace('I', '').replace('L', '')
    return ''.join(random.choices(characters, k=length))


async def is_code_unique(db: AsyncSession, code: str) -> bool:
    """检查邀请码是否唯一"""
    stmt = select(ReferralCode).where(ReferralCode.referral_code == code)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is None


async def generate_unique_code(db: AsyncSession, max_attempts: int = 10) -> str:
    """生成唯一的邀请码"""
    for _ in range(max_attempts):
        code = generate_referral_code()
        if await is_code_unique(db, code):
            return code
    raise Exception("Failed to generate unique referral code after maximum attempts")


def get_code_expiry_date(days: int = 365) -> datetime:
    """获取邀请码过期时间（默认1年）"""
    return datetime.now(timezone.utc) + timedelta(days=days)


def is_code_expired(expires_at: datetime) -> bool:
    """检查邀请码是否过期"""
    if expires_at is None:
        return False
    return datetime.now(timezone.utc) > expires_at