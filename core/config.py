from pydantic_settings import BaseSettings
import base64

class Settings(BaseSettings):
    # 数据库连接参数
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    
    supabase_url: str
    supabase_key: str

    stripe_api_key: str
    stripe_webhook_secret: str

    encryption_key:str

    email_salt:str

    apple_shared_secret:str

    # 一次性(one-off) Stripe price ID
    stripe_price_year_pro: str
    stripe_price_year_team: str
    stripe_price_pack_10: str
    stripe_price_pack_30: str
    stripe_price_pack_50: str

    class Config:
        env_file = ".env"
    
    @property
    def encryption_key_bytes(self) -> bytes:
        """Convert base64 encoded key to bytes"""
        return base64.b64decode(self.encryption_key)
    
    @property
    def database_url(self) -> str:
        """Construct database URL from individual components"""
        import urllib.parse
        password = urllib.parse.quote_plus(self.db_password)
        return f"postgresql+asyncpg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def stripe_price_map(self) -> dict:
        """price_id -> 产品类型映射，webhook收到 checkout.session.completed 时用来识别具体买的什么"""
        return {
            self.stripe_price_year_pro: {"type": "annual", "plan": "pro"},
            self.stripe_price_year_team: {"type": "annual", "plan": "team"},
            self.stripe_price_pack_10: {"type": "credit_pack", "credits": 10},
            self.stripe_price_pack_30: {"type": "credit_pack", "credits": 30},
            self.stripe_price_pack_50: {"type": "credit_pack", "credits": 50},
        }
    
settings = Settings()