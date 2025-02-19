from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum

class RequestStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class FriendRequestBase(SQLModel):
    sender_id: int = Field(foreign_key="user.user_id")
    receiver_id: int = Field(foreign_key="user.user_id")
    status: RequestStatus = Field(default=RequestStatus.PENDING)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FriendRequest(FriendRequestBase, table=True):
    request_id: Optional[int] = Field(default=None, primary_key=True)

class FriendRequestPublic(SQLModel):
    user_id: int
    username: str
    display_name: str
    profile_picture: Optional[str]
    status: RequestStatus