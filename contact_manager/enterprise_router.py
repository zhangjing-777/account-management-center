from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.dialects.postgresql import insert
from core.database import get_db
from core.models import EnterpriseContact
from core.encryption import encrypt_data, decrypt_value
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact for enterprise"])

class EnterpriseContactRequest(BaseModel):
    company_email: str
    company_name: str
    industry: str
    number_employees: str
    message: str

@router.post("/enterprise-insert-update")
async def enterprise_contact_process(body: EnterpriseContactRequest, db: AsyncSession = Depends(get_db)):
    """处理企业联系表单，写入 enterprise_contact 表 (email, company_name, industry, message 加密)"""
    try:
        logger.info(f"Enterprise contact form received: email={body.company_email}")

        encrypted_data = encrypt_data("enterprise_contact", {
            "email": body.company_email,
            "company_name": body.company_name,
            "industry": body.industry,
            "message": body.message,
        })

        now = datetime.now(timezone.utc)

        stmt = insert(EnterpriseContact).values(
            email=encrypted_data["email"],
            email_hash=func.encode(func.digest(body.company_email, 'sha256'), 'hex'),
            company_name=encrypted_data["company_name"],
            industry=encrypted_data["industry"],
            number_employees=body.number_employees,
            message=encrypted_data["message"],
            created_at=now,
            updated_at=now
        ).on_conflict_do_update(
            index_elements=['email_hash'],
            set_={
                'company_name': encrypted_data["company_name"],
                'industry': encrypted_data["industry"],
                'number_employees': body.number_employees,
                'message': encrypted_data["message"],
                'updated_at': now
            }
        ).returning(EnterpriseContact)

        result = await db.execute(stmt)
        record = result.scalar_one()
        await db.commit()

        logger.info(f"Enterprise contact upsert success: id={record.id} email={body.company_email}")

        return {
            "message": "Enterprise contact saved successfully",
            "data": {
                "id": record.id,
                "email": record.email,
                "company_name": record.company_name,
                "industry": record.industry,
                "number_employees": record.number_employees,
                "message": record.message,
                "created_at": record.created_at,
                "updated_at": record.updated_at
            },
            "status": "success"
        }

    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to process enterprise contact form: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/enterprise-check")
async def get_enterprise_contact(email: str = Query(..., description="企业邮箱"), db: AsyncSession = Depends(get_db)):
    """根据 email 查询 enterprise_contact 记录并解密"""
    try:
        logger.info(f"Querying enterprise_contact by email={email}")

        stmt = select(EnterpriseContact).where(
            EnterpriseContact.email_hash == func.encode(func.digest(email, 'sha256'), 'hex')
        )
        
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return {"message": "No enterprise contact found", "status": "success", "data": None}

        decrypted = {
            "id": record.id,
            "email": decrypt_value(record.email),
            "company_name": decrypt_value(record.company_name),
            "industry": decrypt_value(record.industry),
            "number_employees": record.number_employees,
            "message": decrypt_value(record.message),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

        return {"message": "Query success", "status": "success", "data": decrypted}

    except Exception as e:
        logger.exception(f"Failed to query enterprise contact by email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/enterprise-delete")
async def delete_enterprise_contact(
    id: int = Query(None, description="记录主键 id"),
    email: str = Query(None, description="企业邮箱"),
    db: AsyncSession = Depends(get_db)
):
    """删除 enterprise_contact 表记录（支持 id 或 email）"""
    try:
        if not id and not email:
            raise HTTPException(status_code=400, detail="必须提供 id 或 email")

        if id:
            stmt = delete(EnterpriseContact).where(EnterpriseContact.id == id).returning(EnterpriseContact.id)
        else:
            stmt = delete(EnterpriseContact).where(
                EnterpriseContact.email_hash == func.encode(func.digest(email, 'sha256'), 'hex')
            ).returning(EnterpriseContact.id)

        result = await db.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        await db.commit()

        if not deleted_id:
            return {"message": "Record not found", "deleted": False, "status": "failed"}

        return {
            "message": "Enterprise contact deleted successfully",
            "deleted": True,
            "id": deleted_id,
            "status": "success"
        }

    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to delete enterprise contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))
