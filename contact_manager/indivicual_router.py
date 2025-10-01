from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncpg
import logging
from encryption import encrypt_data, decrypt_value
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact for individual"])

# 输入模型
class ContactRequest(BaseModel):
    email: str
    first_name: str
    last_name: str
    message: str


@router.post("/individual-insert-update")
async def contact_process(body: ContactRequest):
    """处理 Contact Us 表单提交，写入 contact 表"""
    try:
        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)
        logger.info(f"Contact form received: email={body.email}")

        # --- 加密数据 ---
        encrypted_data = encrypt_data("contact", {
            "email": body.email,
            "first_name": body.first_name,
            "last_name": body.last_name,
            "message": body.message,
        })

        now = datetime.now(timezone.utc)

        # --- UPSERT 插入/更新 ---
        query = """
        INSERT INTO public.contact (email, email_hash, first_name, last_name, message, created_at, updated_at)
        VALUES ($1, encode(digest($2, 'sha256'), 'hex'), $3, $4, $5, $6, $6)
        ON CONFLICT (email_hash)
        DO UPDATE SET 
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            message = EXCLUDED.message,
            updated_at = EXCLUDED.updated_at
        RETURNING id, email, first_name, last_name, message, created_at, updated_at;
        """

        record = await conn.fetchrow(
            query,
            encrypted_data["email"],  # 存密文
            body.email,               # email 原文用于生成 email_hash
            encrypted_data["first_name"],
            encrypted_data["last_name"],
            encrypted_data["message"],
            now,
        )

        await conn.close()
        logger.info(f"Contact upsert success for email={body.email}, id={record['id']}")

        return {
            "message": "Contact saved successfully",
            "data": dict(record),
            "status": "success"
        }

    except Exception as e:
        logger.exception(f"Failed to process contact form: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/individual-check")
async def get_contact(email: str = Query(..., description="用户邮箱")):
    """根据 email 查询 contact 表记录，并解密返回"""
    try:
        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)
        logger.info(f"Querying contact by email={email}")

        # 计算 email_hash
        query = """
        SELECT id, email, first_name, last_name, message, created_at, updated_at
        FROM public.contact
        WHERE email_hash = encode(digest($1, 'sha256'), 'hex')
        LIMIT 1;
        """
        record = await conn.fetchrow(query, email)
        await conn.close()

        if not record:
            return {"message": "No contact record found", "status": "success", "data": None}

        # 解密字段
        decrypted = {
            "id": record["id"],
            "email": decrypt_value(record["email"]),
            "first_name": decrypt_value(record["first_name"]),
            "last_name": decrypt_value(record["last_name"]),
            "message": decrypt_value(record["message"]),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

        logger.info(f"Contact record found for email={email}, id={record['id']}")
        return {"message": "Query success", "status": "success", "data": decrypted}

    except Exception as e:
        logger.exception(f"Failed to query contact by email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/individual-delete")
async def delete_contact(
    id: int = Query(None, description="记录主键 id"),
    email: str = Query(None, description="用户邮箱")
):
    """删除 contact 表记录（支持 id 或 email）"""
    try:
        if not id and not email:
            raise HTTPException(status_code=400, detail="必须提供 id 或 email")

        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)

        if id:
            query = "DELETE FROM public.contact WHERE id = $1 RETURNING id;"
            record = await conn.fetchrow(query, id)
        else:
            query = """
            DELETE FROM public.contact
            WHERE email_hash = encode(digest($1, 'sha256'), 'hex')
            RETURNING id;
            """
            record = await conn.fetchrow(query, email)

        await conn.close()

        if not record:
            return {"message": "Record not found", "deleted": False, "status": "failed"}

        return {"message": "Record deleted successfully", "deleted": True, "id": record["id"], "status": "success"}

    except Exception as e:
        logger.exception(f"Failed to delete contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))
