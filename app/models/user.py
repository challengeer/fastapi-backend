from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class UserBase(SQLModel):
    username: str = Field(index=True, unique=True, max_length=15)
    display_name: str = Field(index=True, unique=False, max_length=30)
    profile_picture: Optional[str] = Field(nullable=True, max_length=255)
    email: Optional[str] = Field(nullable=True, index=True, unique=True, max_length=100)
    phone_number: Optional[str] = Field(nullable=True, index=True, unique=True, max_length=15)
    google_id: Optional[str] = Field(nullable=True, index=True, unique=True, max_length=100)
    password: Optional[str] = Field(nullable=True, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class User(UserBase, table=True):
    user_id: Optional[int] = Field(default=None, primary_key=True)

class UserPublic(SQLModel):
    user_id: int
    display_name: str
    username: str
    profile_picture: Optional[str]

class UserUpdate(UserBase):
    pass