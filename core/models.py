from sqlalchemy import Column, String, Integer, DateTime, func, Text, Date, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base


class UserLevelEn(Base):
    __tablename__ = "user_level_en"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(Text, nullable=False)
    email_hash = Column(String, unique=True, nullable=False)
    subscription_status = Column(Text)
    paypal_subscription_id = Column(Text)
    virtual_box = Column(Text)
    stripe_customer_id = Column(Text)
    apple_customer_id = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ReceiptUsageQuotaReceiptEn(Base):
    __tablename__ = "receipt_usage_quota_receipt_en"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(Text, nullable=False)
    email_hash = Column(String, unique=True, nullable=False)
    month_limit = Column(Integer, default=0)
    raw_limit = Column(Integer, default=50)
    used_month = Column(Integer, default=0)
    last_reset_date = Column(Date)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ReceiptUsageQuotaRequestEn(Base):
    __tablename__ = "receipt_usage_quota_request_en"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(Text, nullable=False)
    email_hash = Column(String, unique=True, nullable=False)
    month_limit = Column(Integer, default=0)
    raw_limit = Column(Integer, default=50)
    used_month = Column(Integer, default=0)
    last_reset_date = Column(Date)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Contact(Base):
    __tablename__ = "contact"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, nullable=False)
    email_hash = Column(String, unique=True, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class EnterpriseContact(Base):
    __tablename__ = "enterprise_contact"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, nullable=False)
    email_hash = Column(String, unique=True, nullable=False)
    company_name = Column(String)
    industry = Column(String)
    number_employees = Column(String)
    message = Column(Text)
    created_at = Column(DateTime(timezone=False))
    updated_at = Column(DateTime(timezone=False))

class ReferralCode(Base):
    """邀请码表"""
    __tablename__ = "referral_codes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    referral_code = Column(String(6), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True))  # 邀请码过期时间（可选）
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReferralRecord(Base):
    """推荐记录表"""
    __tablename__ = "referral_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_user_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # 推荐人
    referee_user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)  # 被邀请人（unique确保只能被邀请一次）
    referral_code = Column(String(6), nullable=False)
    credit_amount = Column(Numeric(10, 2), default=1.00)  # 返利金额（欧元）
    status = Column(String(20), default='pending')  # pending, completed, expired
    payment_intent_id = Column(String)  # Stripe Payment Intent ID
    stripe_customer_id = Column(String)  # Stripe Customer ID
    credited_at = Column(DateTime(timezone=True))  # 返利到账时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserCredit(Base):
    """用户余额表"""
    __tablename__ = "user_credits"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    total_credits = Column(Numeric(10, 2), default=0.00)  # 总余额
    used_credits = Column(Numeric(10, 2), default=0.00)  # 已使用余额
    available_credits = Column(Numeric(10, 2), default=0.00)  # 可用余额
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CreditTransaction(Base):
    """余额变动记录表"""
    __tablename__ = "credit_transactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    transaction_type = Column(String(20), nullable=False)  # earned（获得）, used（使用）, expired（过期）
    amount = Column(Numeric(10, 2), nullable=False)
    balance_before = Column(Numeric(10, 2))  # 交易前余额
    balance_after = Column(Numeric(10, 2))  # 交易后余额
    description = Column(String(255))  # 描述
    reference_id = Column(String)  # 关联ID（如referral_record_id或stripe_invoice_id）
    created_at = Column(DateTime(timezone=True), server_default=func.now())