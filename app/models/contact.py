from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class ContactBase(SQLModel):
    user_id: int = Field(foreign_key="user.user_id", index=True)
    contact_name: str = Field(max_length=100)
    phone_number: str = Field(max_length=15)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Contact(ContactBase, table=True):
    contact_id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        sa_column_kwargs = {
            "user_id,phone_number": {"unique": True}  # One contact per phone number per user
        }

class ContactCreate(SQLModel):
    contact_name: str
    phone_number: str

class ContactBatchCreate(SQLModel):
    contacts: list[ContactCreate] 