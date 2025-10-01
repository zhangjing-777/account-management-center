from fastapi import APIRouter
from auth_new_user.services import do_sync_new_users

router = APIRouter(prefix="/users", tags=["同步新用户"])

@router.post("/sync-new-users")
async def sync_new_users():
    return await do_sync_new_users()
    