from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class UserBase(SQLModel):
    username: str = Field(index=True, unique=True)
    display_name: str = Field(index=True, unique=False)
    email: str = Field(index=True, unique=True)
    phone_number: str = Field(index=True, unique=True)
    password: Optional[str] = Field(nullable=True)
    profile_picture: Optional[str] = Field(nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class User(UserBase, table=True):
    user_id: Optional[int] = Field(default=None, primary_key=True)

class UserCreate(UserBase):
    pass

class UserPublic(SQLModel):
    user_id: int
    display_name: str
    username: str
    profile_picture: Optional[str]

class UserUpdate(UserBase):
    pass