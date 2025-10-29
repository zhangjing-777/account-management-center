from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from core.database import get_db
from core.models import UserCredit, CreditTransaction
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe Credit Management"])


class GetCreditRequest(BaseModel):
    user_id: str


@router.post("/credits")
async def get_user_credits(
    request: GetCreditRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    查询用户余额
    
    返回：
    - 总余额
    - 已使用余额
    - 可用余额
    """
    try:
        user_id = request.user_id
        logger.info(f"Getting credits for user_id: {user_id}")
        
        stmt = select(UserCredit).where(UserCredit.user_id == user_id)
        result = await db.execute(stmt)
        credit = result.scalar_one_or_none()
        
        if not credit:
            # 如果没有记录，返回0余额
            return {
                "message": "No credits found",
                "data": {
                    "user_id": user_id,
                    "total_credits": 0.00,
                    "used_credits": 0.00,
                    "available_credits": 0.00
                },
                "status": "success"
            }
        
        return {
            "message": "Credits retrieved successfully",
            "data": {
                "user_id": user_id,
                "total_credits": float(credit.total_credits),
                "used_credits": float(credit.used_credits),
                "available_credits": float(credit.available_credits),
                "updated_at": credit.updated_at
            },
            "status": "success"
        }
        
    except Exception as e:
        logger.exception(f"Failed to get user credits: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/credit-history")
async def get_credit_history(
    request: GetCreditRequest,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    查询余额变动历史
    
    参数：
    - limit: 返回记录数量（默认50，最大100）
    
    返回交易历史列表
    """
    try:
        user_id = request.user_id
        logger.info(f"Getting credit history for user_id: {user_id}, limit: {limit}")
        
        stmt = (
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
            .order_by(desc(CreditTransaction.created_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        transactions = result.scalars().all()
        
        transaction_list = [
            {
                "id": tx.id,
                "transaction_type": tx.transaction_type,
                "amount": float(tx.amount),
                "balance_before": float(tx.balance_before) if tx.balance_before else 0.00,
                "balance_after": float(tx.balance_after) if tx.balance_after else 0.00,
                "description": tx.description,
                "reference_id": tx.reference_id,
                "created_at": tx.created_at
            }
            for tx in transactions
        ]
        
        return {
            "message": "Credit history retrieved successfully",
            "data": {
                "user_id": user_id,
                "total_records": len(transaction_list),
                "transactions": transaction_list
            },
            "status": "success"
        }
        
    except Exception as e:
        logger.exception(f"Failed to get credit history: {e}")
        raise HTTPException(status_code=500, detail=str(e))