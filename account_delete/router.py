from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import logging

load_dotenv()

# Initialize Supabase admin client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["ReceiptDrop Account Deletion"])

# Request model
class DeleteAccountRequest(BaseModel):
    user_id: str  # Supabase Auth UID (from client)


TABLES_CLEAN_4UID = [
            "subscription_records",
            "user_level_en",
            "user_email_tokens",
            "ses_eml_info_en",
            "receipt_usage_quota_request_en",
            "receipt_usage_quota_receipt_en",
            "receipt_summary_zip_en",
            "receipt_mobile_voice_message_en",
            "receipt_items_en_upload_result",
            "receipt_items_en",
            "imported_emails",
            "gmail_confirm_link_en",
            "canonical_entities"
        ]

TABLES_CLEAN_4EMAIL = [
            "enterprise_contact",
            "contact"
        ]

# Storage configuration
STORAGE_BUCKET = "receiptDrop"
STORAGE_PATHS = ["save", "summary"]

def delete_storage_files_sql(user_id: str) -> dict:
    """
    使用SQL直接从storage.objects表删除文件（最快的方法）
    删除 receiptDrop bucket 中 save/{user_id} 和 summary/{user_id} 下的所有内容
    
    Args:
        user_id: 用户ID
        
    Returns:
        包含删除结果的字典
    """
    deletion_results = {
        "save": {"deleted": 0, "errors": []},
        "summary": {"deleted": 0, "errors": []}
    }
    
    for path_prefix in STORAGE_PATHS:
        user_path = f"{path_prefix}/{user_id}"
        
        try:
            logger.info(f"Attempting to delete files via SQL in bucket '{STORAGE_BUCKET}' at path '{user_path}%'")
            
            # 使用SQL直接从storage.objects表删除（最快的方法）
            # 这会删除所有匹配路径前缀的文件，包括所有子目录
            result = supabase.schema('storage').from_('objects').delete().eq(
                'bucket_id', STORAGE_BUCKET
            ).like('name', f'{user_path}%').execute()
            
            # 统计删除的记录数
            deleted_count = len(result.data) if result.data else 0
            deletion_results[path_prefix]["deleted"] = deleted_count
            
            logger.info(f"Successfully deleted {deleted_count} files from '{user_path}' via SQL")
                
        except Exception as e:
            error_msg = f"Error deleting from path '{user_path}': {str(e)}"
            logger.error(error_msg)
            deletion_results[path_prefix]["errors"].append(error_msg)
    
    return deletion_results


@router.post("/delete_account")
async def delete_account(req: DeleteAccountRequest):
    """
    Permanently delete user account and all associated records from Supabase.
    This endpoint is intended to satisfy Apple's App Review Guideline 5.1.1(v).
    """
    try:
        user_id = req.user_id.strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        logger.info(f"Starting account deletion for user_id: {user_id}")

        # 1. Delete files from Supabase Storage using SQL (fastest method)
        storage_deletion_results = delete_storage_files_sql(user_id)
        logger.info(f"Storage deletion results: {storage_deletion_results}")

        # 2. Delete related database records        
        for table in TABLES_CLEAN_4UID:
            try:
                supabase.table(table).delete().eq("user_id", user_id).execute()
                logger.info(f"Deleted records from table '{table}' for user_id: {user_id}")
            except Exception as e:
                # Ignore if table doesn't exist or field missing
                logger.warning(f"Could not delete from table '{table}': {str(e)}")
                pass

        # 3. Delete the auth user
        try:
            supabase.auth.admin.delete_user(user_id)
            logger.info(f"Deleted auth user: {user_id}")
        except Exception as e:
            # In case user is already gone or invalid ID
            logger.warning(f"Auth user deletion issue: {e}")

        # Return confirmation
        return {
            "status": "success",
            "message": f"Account {user_id} and related data deleted.",
            "details": {
                "storage_deletion": storage_deletion_results,
                "database_tables_processed": len(TABLES_CLEAN_4UID)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Account deletion failed for user_id: {user_id}")
        raise HTTPException(status_code=500, detail=str(e))
    