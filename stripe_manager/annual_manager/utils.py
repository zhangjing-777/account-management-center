import random
import string
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import AnnualRedeemCode


def generate_activation_code(length: int = 10) -> str:
    """生成年度激活码，字母数字组合，去掉易混淆字符"""
    characters = string.ascii_uppercase + string.digits
    characters = (
        characters.replace("O", "").replace("I", "")
        .replace("L", "").replace("0", "").replace("1", "")
    )
    return "".join(random.choices(characters, k=length))


async def generate_unique_annual_code(db: AsyncSession, max_attempts: int = 10) -> str:
    """生成唯一的激活码（对着 annual_redeem_codes 表查重）"""
    for _ in range(max_attempts):
        code = generate_activation_code()
        stmt = select(AnnualRedeemCode).where(AnnualRedeemCode.code == code)
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            return code
    raise Exception("Failed to generate unique annual code after maximum attempts")