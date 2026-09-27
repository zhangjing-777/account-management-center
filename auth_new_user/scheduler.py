from apscheduler.schedulers.asyncio import AsyncIOScheduler
from auth_new_user.services import do_sync_new_users
from stripe_manager.annual_manager.expiry_service import do_check_annual_expiry 
import logging

logger = logging.getLogger(__name__)


class JobScheduler:
    """Handle scheduled tasks"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        logger.info("Job scheduler initialized")
    
    async def sync_new_users_job(self):
        """Scheduled job to sync new users"""
        try:
            logger.info("Running scheduled user synchronization")
            result = await do_sync_new_users()
            logger.info(f"Scheduled sync completed: {result}")
        except Exception as e:
            logger.error(f"Scheduled user sync failed: {e}")

    async def check_annual_expiry_job(self):  
        """每日检查年度订阅到期/续期"""
        try:
            logger.info("Running scheduled annual subscription expiry check")
            await do_check_annual_expiry()
        except Exception as e:
            logger.error(f"Scheduled annual expiry check failed: {e}")

    def start(self):
        """Start the scheduler"""
        # Add job to run every 60 seconds (adjust as needed)
        self.scheduler.add_job(
            self.sync_new_users_job,
            'interval',
            seconds=30,
            id='sync_new_users',
            replace_existing=True
        )

        self.scheduler.add_job(  # 每天凌晨3点跑一次
            self.check_annual_expiry_job,
            'cron',
            hour=3,
            id='check_annual_expiry',
            replace_existing=True
        )

        self.scheduler.start()
        logger.info("Job scheduler started")
    
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Job scheduler stopped")


# Global scheduler instance
job_scheduler = JobScheduler()