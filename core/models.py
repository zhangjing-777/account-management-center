from sqlalchemy import Column, String, Integer, DateTime, func, Text, Date
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
    month_limit = Column(Integer, default=5)
    used_month = Column(Integer, default=0)
    last_reset_date = Column(Date)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ReceiptUsageQuotaRequestEn(Base):
    __tablename__ = "receipt_usage_quota_request_en"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(Text, nullable=False)
    email_hash = Column(String, unique=True, nullable=False)
    month_limit = Column(Integer, default=5)
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