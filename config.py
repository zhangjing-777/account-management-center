from pydantic_settings import BaseSettings

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

    class Config:
        env_file = ".env"
    
    @property
    def database_url(self) -> str:
        """Construct database URL from individual components"""
        import urllib.parse
        password = urllib.parse.quote_plus(self.db_password)
        return f"postgresql://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()