import os
import logging
from datetime import datetime
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from core.database import close_db
from auth_new_user.scheduler import job_scheduler
from account_check.router import router as account_check_routers
from auth_new_user.router import router as auth_new_user_routers
from contact_manager.enterprise_router import router as contact_enterprise_routers
from contact_manager.indivicual_router import router as contact_individual_routers
from stripe_manager.paid_router import router as stripe_paid_routers
from stripe_manager.subscript_router import router as stripe_subscript_routers
from stripe_manager.webhook_handle_router import router as stripe_webhook_routers
from account_delete.router import router as delete_account_routers

os.makedirs('logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(f'logs/app_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting User Management API")
    job_scheduler.start()
    logger.info("Application startup completed")
    
    yield
    
    logger.info("Shutting down User Management API")
    job_scheduler.stop()
    await close_db()
    logger.info("Application shutdown completed")

app = FastAPI(
    title="User Management API",
    description="FastAPI service for managing users with encrypted email storage (EU GDPR compliant)",
    version="1.0.0",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account_check_routers)
app.include_router(auth_new_user_routers)
app.include_router(stripe_paid_routers)
app.include_router(stripe_subscript_routers)
app.include_router(stripe_webhook_routers)
app.include_router(contact_enterprise_routers)
app.include_router(contact_individual_routers)
app.include_router(delete_account_routers)

@app.get("/health")
async def health_check():
    logger.info("Health check requested")
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception occurred: {str(exc)}")
    return {"error": "Internal server error", "status": "error"}
