from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncpg
import logging
from encryption import encrypt_data, decrypt_value
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact for enterprise"])


# 输入模型
class EnterpriseContactRequest(BaseModel):
    company_email: str
    company_name: str
    industry: str
    number_employees: str
    message: str


@router.post("/enterprise-insert-update")
async def enterprise_contact_process(body: EnterpriseContactRequest):
    """处理企业联系表单，写入 enterprise_contact 表 (email, company_name, industry, message 加密)"""
    try:
        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)
        logger.info(f"Enterprise contact form received: email={body.company_email}")

        # --- 加密敏感字段 ---
        encrypted_data = encrypt_data("enterprise_contact", {
            "email": body.company_email,
            "company_name": body.company_name,
            "industry": body.industry,
            "message": body.message,
        })

        now = datetime.now()

        # --- UPSERT 插入/更新 ---
        query = """
        INSERT INTO public.enterprise_contact 
            (email, email_hash, company_name, industry, number_employees, message, created_at, updated_at)
        VALUES 
            ($1, encode(digest($2, 'sha256'), 'hex'), $3, $4, $5, $6, $7, $7)
        ON CONFLICT (email_hash)
        DO UPDATE SET 
            company_name = EXCLUDED.company_name,
            industry = EXCLUDED.industry,
            number_employees = EXCLUDED.number_employees,
            message = EXCLUDED.message,
            updated_at = EXCLUDED.updated_at
        RETURNING id, email, company_name, industry, number_employees, message, created_at, updated_at;
        """

        record = await conn.fetchrow(
            query,
            encrypted_data["email"],  # 存密文
            body.company_email,       # 原文用于生成 hash
            encrypted_data["company_name"],
            encrypted_data["industry"],
            body.number_employees,    # number_employees 不加密
            encrypted_data["message"],
            now,
        )

        await conn.close()
        logger.info(f"Enterprise contact upsert success: id={record['id']} email={body.company_email}")

        return {
            "message": "Enterprise contact saved successfully",
            "data": dict(record),
            "status": "success"
        }

    except Exception as e:
        logger.exception(f"Failed to process enterprise contact form: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 查询接口（通过 email 获取并解密） ==========
@router.get("/enterprise-check")
async def get_enterprise_contact(email: str):
    """根据 email 查询 enterprise_contact 记录并解密"""
    try:
        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)
        logger.info(f"Querying enterprise_contact by email={email}")

        query = """
        SELECT id, email, company_name, industry, number_employees, message, created_at, updated_at
        FROM public.enterprise_contact
        WHERE email_hash = encode(digest($1, 'sha256'), 'hex')
        LIMIT 1;
        """
        record = await conn.fetchrow(query, email)
        await conn.close()

        if not record:
            return {"message": "No enterprise contact found", "status": "success", "data": None}

        # --- 解密 ---
        decrypted = {
            "id": record["id"],
            "email": decrypt_value(record["email"]),
            "company_name": decrypt_value(record["company_name"]),
            "industry": decrypt_value(record["industry"]),
            "number_employees": record["number_employees"],
            "message": decrypt_value(record["message"]),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

        return {"message": "Query success", "status": "success", "data": decrypted}

    except Exception as e:
        logger.exception(f"Failed to query enterprise contact by email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/enterprise-delete")
async def delete_enterprise_contact(
    id: int = Query(None, description="记录主键 id"),
    email: str = Query(None, description="企业邮箱")
):
    """删除 enterprise_contact 表记录（支持 id 或 email）"""
    try:
        if not id and not email:
            raise HTTPException(status_code=400, detail="必须提供 id 或 email")

        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)

        if id:
            query = "DELETE FROM public.enterprise_contact WHERE id = $1 RETURNING id;"
            record = await conn.fetchrow(query, id)
        else:
            query = """
            DELETE FROM public.enterprise_contact
            WHERE email_hash = encode(digest($1, 'sha256'), 'hex')
            RETURNING id;
            """
            record = await conn.fetchrow(query, email)

        await conn.close()

        if not record:
            return {"message": "Record not found", "deleted": False, "status": "failed"}

        return {"message": "Enterprise contact deleted successfully", "deleted": True, "id": record["id"], "status": "success"}

    except Exception as e:
        logger.exception(f"Failed to delete enterprise contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))
