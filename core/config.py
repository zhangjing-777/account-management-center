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

        # ---------- Apple IAP (StoreKit 2 / App Store Server Notifications V2) ----------
    # 允许的 App bundle id，逗号分隔（ReceiptDrop 和 ReceiptTalk 共用这个后端）
    apple_bundle_ids: str = ""                   # 例: "com.abeeva.receiptdrop,com.abeeva.receipttalk"
    # 生产环境验签必须提供 App Apple ID（App Store Connect → App 信息 → Apple ID，一串数字）
    apple_app_apple_ids: str = ""                # 例: "com.abeeva.receiptdrop=6470000001,com.abeeva.receipttalk=6470000002"
    # Apple 根证书目录（放 AppleRootCA-G3.cer 等 .cer 文件）
    apple_root_cert_dir: str = "certs/apple"
    # 是否接受 Sandbox 交易（App 审核用的就是 Sandbox，必须为 True）
    apple_allow_sandbox: bool = True

    # 3 个商品的 Product ID（和 App Store Connect 里建的完全一致）
    apple_product_plus_monthly: str = "receipttalk.plus.monthly"
    apple_product_receipts_100: str = "receipttalk.receipts.100"
    apple_product_voice_100min: str = "receipttalk.voice.100min"
    # 旧版 ReceiptDrop 已上架的 Pro 订阅 Product ID（逗号分隔），也按 Plus 处理
    apple_legacy_pro_product_ids: str = ""

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

    @property
    def apple_bundle_id_list(self) -> list[str]:
        return [b.strip() for b in self.apple_bundle_ids.split(",") if b.strip()]

    @property
    def apple_app_apple_id_map(self) -> dict[str, int]:
        result = {}
        for pair in self.apple_app_apple_ids.split(","):
            if "=" in pair:
                bundle_id, app_id = pair.split("=", 1)
                result[bundle_id.strip()] = int(app_id.strip())
        return result

    @property
    def apple_product_map(self) -> dict:
        """product_id -> 权益。和 stripe_price_map 同样的思路"""
        subscription = {"type": "subscription", "plan": "pro"}
        mapping = {
            self.apple_product_plus_monthly: subscription,
            self.apple_product_receipts_100: {"type": "receipt_pack", "receipts": 100},
            self.apple_product_voice_100min: {"type": "voice_pack", "seconds": 100 * 60},
        }
        for legacy_id in self.apple_legacy_pro_product_ids.split(","):
            if legacy_id.strip():
                mapping[legacy_id.strip()] = subscription
        return mapping
    
settings = Settings()