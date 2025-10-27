import hashlib
from core.config import settings

def generate_email_hash(email: str):
    value = f"{email.lower()}::{settings.email_salt}"
    return hashlib.sha256(value.encode()).hexdigest()
