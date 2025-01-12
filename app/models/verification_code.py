from sqlmodel import SQLModel, Field
from datetime import datetime, timezone

class VerificationCode(SQLModel, table=True):
    phone_number: str = Field(primary_key=True, max_length=15, nullable=False)
    verification_code: str = Field(max_length=6, nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(nullable=False)
    verified: bool = Field(default=False)

class VerificationCodeCreate(SQLModel):
    phone_number: str

class VerificationCodeVerify(SQLModel):
    phone_number: str
    verification_code: str