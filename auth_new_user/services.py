from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging
from core.encryption import encrypt_value
from core.database import AsyncSessionLocal
from core.utils import generate_email_hash
from core.models import UserLevelEn, ReceiptUsageQuotaReceiptEn, ReceiptUsageQuotaRequestEn

logger = logging.getLogger(__name__)

async def do_sync_new_users():
    async with AsyncSessionLocal() as db:
        try:
            logger.info("Starting sync_new_users job...")

            query = text("""
                SELECT u.id, u.email
                FROM auth.users u
                LEFT JOIN public.user_level_en ul ON ul.user_id = u.id
                WHERE ul.user_id IS NULL;
            """)
            
            result = await db.execute(query)
            rows = result.fetchall()
            
            logger.info(f"Found {len(rows)} new users to sync")

            if not rows:
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

            user_level_objects = []
            receipt_objects = []
            request_objects = []

            for row in rows:
                user_id = row.id
                email_plain = row.email

                try:
                    encrypted_email = encrypt_value(email_plain)
                except Exception as e:
                    logger.error(f"Failed to encrypt email for user_id={user_id}: {e}")
                    continue

                user_level_objects.append(
                    UserLevelEn(
                        user_id=user_id,
                        email=encrypted_email,
                        email_hash=generate_email_hash(email_plain),
                        subscription_status="free",
                        virtual_box=f"{user_id}@inbox.receiptdrop.dev"
                    )
                )
                
                receipt_objects.append(
                    ReceiptUsageQuotaReceiptEn(
                        user_id=user_id,
                        email=encrypted_email,
                        email_hash=generate_email_hash(email_plain),
                        used_month=0,
                        month_limit=0,
                        raw_limit=50
                    )
                )
                
                request_objects.append(
                    ReceiptUsageQuotaRequestEn(
                        user_id=user_id,
                        email=encrypted_email,
                        email_hash=generate_email_hash(email_plain),
                        used_month=0,
                        month_limit=0,
                        raw_limit=50
                    )
                )

            if user_level_objects:
                db.add_all(user_level_objects)
                logger.info(f"Added {len(user_level_objects)} records to user_level_en")

            if receipt_objects:
                db.add_all(receipt_objects)
                logger.info(f"Added {len(receipt_objects)} records to receipt_usage_quota_receipt_en")

            if request_objects:
                db.add_all(request_objects)
                logger.info(f"Added {len(request_objects)} records to receipt_usage_quota_request_en")

            await db.commit()
            logger.info("All records committed successfully")

            return {
                "message": "Sync completed",
                "inserted": {
                    "user_level_en": len(user_level_objects),
                    "receipt_usage_quota_receipt_en": len(receipt_objects),
                    "receipt_usage_quota_request_en": len(request_objects)
                },
                "status": "success"
            }

        except Exception as e:
            await db.rollback()
            logger.exception(f"sync_new_users failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


