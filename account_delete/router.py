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
            "gmail_confirm_link_en"
        ]

TABLES_CLEAN_4EMAIL = [
            "enterprise_contact",
            "contact"
        ]

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

        # Delete related records        
        for table in TABLES_CLEAN_4UID:
            try:
                supabase.table(table).delete().eq("user_id", user_id).execute()
            except Exception:
                # Ignore if table doesn't exist or field missing
                pass

        # Delete the auth user
        try:
            supabase.auth.admin.delete_user(user_id)
        except Exception as e:
            # In case user is already gone or invalid ID
            print(f"[WARN] Auth user deletion issue: {e}")

        # Return confirmation
        return {
            "status": "success",
            "message": f"Account {user_id} and related data deleted."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

