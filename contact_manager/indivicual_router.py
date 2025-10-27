from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.dialects.postgresql import insert
from core.database import get_db
from core.models import Contact
from core.utils import generate_email_hash
from core.encryption import encrypt_data, decrypt_value
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact for individual"])

class ContactRequest(BaseModel):
    email: str
    first_name: str
    last_name: str
    message: str

@router.post("/individual-insert-update")
async def contact_process(body: ContactRequest, db: AsyncSession = Depends(get_db)):
    try:
        logger.info(f"Contact form received: email={body.email}")

        encrypted_data = encrypt_data("contact", {
            "email": body.email,
            "first_name": body.first_name,
            "last_name": body.last_name,
            "message": body.message,
        })

        now = datetime.now(timezone.utc)

        stmt = insert(Contact).values(
            email=encrypted_data["email"],
            email_hash=generate_email_hash(body.email),
            first_name=encrypted_data["first_name"],
            last_name=encrypted_data["last_name"],
            message=encrypted_data["message"],
            created_at=now,
            updated_at=now
        ).on_conflict_do_update(
            index_elements=['email_hash'],
            set_={
                'first_name': encrypted_data["first_name"],
                'last_name': encrypted_data["last_name"],
                'message': encrypted_data["message"],
                'updated_at': now
            }
        ).returning(Contact)

        result = await db.execute(stmt)
        record = result.scalar_one()
        await db.commit()

        logger.info(f"Contact upsert success for email={body.email}, id={record.id}")

        return {
            "message": "Contact saved successfully",
            "data": {
                "id": record.id,
                "email": record.email,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "message": record.message,
                "created_at": record.created_at,
                "updated_at": record.updated_at
            },
            "status": "success"
        }

    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to process contact form: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/individual-check")
async def get_contact(email: str = Query(..., description="用户邮箱"), db: AsyncSession = Depends(get_db)):
    try:
        logger.info(f"Querying contact by email={email}")

        stmt = select(Contact).where(
            Contact.email_hash == generate_email_hash(email)
        )
        
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return {"message": "No contact record found", "status": "success", "data": None}

        decrypted = {
            "id": record.id,
            "email": decrypt_value(record.email),
            "first_name": decrypt_value(record.first_name),
            "last_name": decrypt_value(record.last_name),
            "message": decrypt_value(record.message),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

        logger.info(f"Contact record found for email={email}, id={record.id}")
        return {"message": "Query success", "status": "success", "data": decrypted}

    except Exception as e:
        logger.exception(f"Failed to query contact by email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/individual-delete")
async def delete_contact(
    id: int = Query(None, description="记录主键 id"),
    email: str = Query(None, description="用户邮箱"),
    db: AsyncSession = Depends(get_db)
):
    try:
        if not id and not email:
            raise HTTPException(status_code=400, detail="必须提供 id 或 email")

        if id:
            stmt = delete(Contact).where(Contact.id == id).returning(Contact.id)
        else:
            stmt = delete(Contact).where(
                Contact.email_hash == generate_email_hash(email)
            ).returning(Contact.id)

        result = await db.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        await db.commit()

        if not deleted_id:
            return {"message": "Record not found", "deleted": False, "status": "failed"}

        return {
            "message": "Record deleted successfully",
            "deleted": True,
            "id": deleted_id,
            "status": "success"
        }

    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to delete contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))
