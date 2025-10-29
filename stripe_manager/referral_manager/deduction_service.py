"""
余额抵扣服务

功能：
1. 检查用户是否有可用余额
2. 在Stripe创建支付时应用抵扣
3. 记录余额使用
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone
from decimal import Decimal
import stripe
from core.config import settings
from core.models import UserCredit, CreditTransaction
import logging

stripe.api_key = settings.stripe_api_key

logger = logging.getLogger(__name__)


async def get_available_credits(db: AsyncSession, user_id: str) -> Decimal:
    """
    获取用户可用余额
    
    Args:
        db: 数据库会话
        user_id: 用户ID
    
    Returns:
        可用余额（Decimal）
    """
    stmt = select(UserCredit).where(UserCredit.user_id == user_id)
    result = await db.execute(stmt)
    credit = result.scalar_one_or_none()
    
    if not credit:
        return Decimal('0.00')
    
    return credit.available_credits


async def apply_credit_to_invoice(
    db: AsyncSession,
    user_id: str,
    stripe_invoice_id: str,
    invoice_amount_cents: int
) -> dict:
    """
    将用户余额应用到Stripe Invoice
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        stripe_invoice_id: Stripe Invoice ID
        invoice_amount_cents: 发票金额（分）
    
    Returns:
        抵扣结果字典
    """
    try:
        available_credits = await get_available_credits(db, user_id)
        
        if available_credits <= 0:
            logger.info(f"User {user_id} has no available credits")
            return {
                "applied": False,
                "reason": "no_credits"
            }
        
        # 将余额转换为分（1欧元 = 100分）
        credit_amount_cents = int(available_credits * 100)
        
        # 计算实际抵扣金额（不能超过发票金额）
        deduction_cents = min(credit_amount_cents, invoice_amount_cents)
        deduction_amount = Decimal(str(deduction_cents / 100))
        
        logger.info(f"Applying credit for user {user_id}: "
                   f"available={available_credits}, deduction={deduction_amount}")
        
        # 在Stripe Invoice上添加抵扣项（负金额）
        try:
            invoice_item = stripe.InvoiceItem.create(
                customer=stripe.Invoice.retrieve(stripe_invoice_id).customer,
                invoice=stripe_invoice_id,
                amount=-deduction_cents,  # 负数表示抵扣
                currency="eur",
                description=f"Account Credit Applied ({deduction_amount} EUR)"
            )
            logger.info(f"Stripe invoice item created: {invoice_item.id}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error when applying credit: {e}")
            return {
                "applied": False,
                "reason": "stripe_error",
                "error": str(e)
            }
        
        # 更新用户余额
        stmt_credit = select(UserCredit).where(UserCredit.user_id == user_id)
        result = await db.execute(stmt_credit)
        user_credit = result.scalar_one()
        
        balance_before = user_credit.available_credits
        new_used = user_credit.used_credits + deduction_amount
        new_available = user_credit.available_credits - deduction_amount
        
        stmt_update = (
            update(UserCredit)
            .where(UserCredit.user_id == user_id)
            .values(
                used_credits=new_used,
                available_credits=new_available,
                updated_at=datetime.now(timezone.utc)
            )
        )
        await db.execute(stmt_update)
        
        # 记录交易历史
        transaction = CreditTransaction(
            user_id=user_id,
            transaction_type='used',
            amount=deduction_amount,
            balance_before=balance_before,
            balance_after=new_available,
            description=f"Credit applied to invoice {stripe_invoice_id}",
            reference_id=stripe_invoice_id
        )
        db.add(transaction)
        
        logger.info(f"Credit deduction successful for user {user_id}: "
                   f"deducted={deduction_amount}, remaining={new_available}")
        
        return {
            "applied": True,
            "deduction_amount": float(deduction_amount),
            "remaining_credits": float(new_available),
            "invoice_item_id": invoice_item.id
        }
        
    except Exception as e:
        logger.exception(f"Failed to apply credit to invoice: {e}")
        raise


async def deduct_credits_for_subscription(
    db: AsyncSession,
    user_id: str,
    stripe_customer_id: str,
    subscription_price_eur: Decimal
) -> dict:
    """
    为订阅支付抵扣余额（在创建订阅前调用）
    
    注意：此函数不直接修改Stripe订阅，而是计算抵扣金额
    实际抵扣需要在Stripe Checkout或Invoice中处理
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        stripe_customer_id: Stripe客户ID
        subscription_price_eur: 订阅价格（欧元）
    
    Returns:
        抵扣信息字典
    """
    try:
        available_credits = await get_available_credits(db, user_id)
        
        if available_credits <= 0:
            return {
                "has_credits": False,
                "deduction_amount": 0.00,
                "final_price": float(subscription_price_eur)
            }
        
        # 计算实际抵扣金额（全额使用余额）
        deduction_amount = min(available_credits, subscription_price_eur)
        final_price = subscription_price_eur - deduction_amount
        
        logger.info(f"Credit deduction calculation for user {user_id}: "
                   f"original_price={subscription_price_eur}, "
                   f"deduction={deduction_amount}, final={final_price}")
        
        return {
            "has_credits": True,
            "available_credits": float(available_credits),
            "deduction_amount": float(deduction_amount),
            "final_price": float(final_price),
            "stripe_customer_id": stripe_customer_id
        }
        
    except Exception as e:
        logger.exception(f"Failed to calculate credit deduction: {e}")
        raise