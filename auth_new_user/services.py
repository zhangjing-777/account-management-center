from fastapi import HTTPException
import asyncpg
import logging
from encryption import encrypt_value
from config import settings


logger = logging.getLogger(__name__)

async def do_sync_new_users():
    try:
        logger.info("Starting sync_new_users job...")

        conn = await asyncpg.connect(dsn=settings.database_url,statement_cache_size=0)
        logger.info("Connected to database")

        # 1. 找出 user_level_en 没有的用户
        logger.info("Querying users not in user_level_en...")
        rows = await conn.fetch("""
            SELECT u.id, u.email
            FROM auth.users u
            LEFT JOIN public.user_level_en ul ON ul.user_id = u.id
            WHERE ul.user_id IS NULL;
        """)
        logger.info(f"Found {len(rows)} new users to sync")

        if not rows:
            await conn.close()
            logger.info("No new users found. Sync finished.")
            return {
                "message": "No new users to sync",
                "inserted": {
                    "user_level_en": 0,
                    "receipt_usage_quota_receipt_en": 0,
                    "receipt_usage_quota_request_en": 0
                },
                "status": "success"
            }

        # 2. 构造插入数据
        user_level_values = []
        receipt_values = []
        request_values = []

        for row in rows:
            user_id = row["id"]
            email_plain = row["email"]

            try:
                encrypted_email = encrypt_value(email_plain)
            except Exception as e:
                logger.error(f"Failed to encrypt email for user_id={user_id}: {e}")
                continue  # 跳过这个用户

            user_level_values.append(
                (user_id, encrypted_email, "free", f"{user_id}@inbox.receiptdrop.dev")
            )
            receipt_values.append((user_id, encrypted_email))
            request_values.append((user_id, encrypted_email))

        logger.info(f"Prepared values: user_level_en={len(user_level_values)}, "
                    f"receipt_usage_quota_receipt_en={len(receipt_values)}, "
                    f"receipt_usage_quota_request_en={len(request_values)}")

        # 3. 批量插入 user_level_en
        if user_level_values:
            await conn.executemany("""
                INSERT INTO public.user_level_en (user_id, email, subscription_status, virtual_box)
                VALUES ($1, $2, $3, $4)
            """, user_level_values)
            logger.info(f"Inserted {len(user_level_values)} records into user_level_en")

        # 4. 批量插入 receipt_usage_quota_receipt_en
        if receipt_values:
            await conn.executemany("""
                INSERT INTO public.receipt_usage_quota_receipt_en (user_id, email)
                VALUES ($1, $2)
            """, receipt_values)
            logger.info(f"Inserted {len(receipt_values)} records into receipt_usage_quota_receipt_en")

        # 5. 批量插入 receipt_usage_quota_request_en
        if request_values:
            await conn.executemany("""
                INSERT INTO public.receipt_usage_quota_request_en (user_id, email)
                VALUES ($1, $2)
            """, request_values)
            logger.info(f"Inserted {len(request_values)} records into receipt_usage_quota_request_en")

        await conn.close()
        logger.info("Database connection closed")

        return {
            "message": "Sync completed",
            "inserted": {
                "user_level_en": len(user_level_values),
                "receipt_usage_quota_receipt_en": len(receipt_values),
                "receipt_usage_quota_request_en": len(request_values)
            },
            "status": "success"
        }

    except Exception as e:
        logger.exception(f"sync_new_users failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
