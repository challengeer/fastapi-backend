from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum

class RequestStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class FriendRequestBase(SQLModel):
    sender_id: int = Field(foreign_key="user.user_id", index=True)
    receiver_id: int = Field(foreign_key="user.user_id", index=True)
    status: RequestStatus = Field(default=RequestStatus.PENDING)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FriendRequest(FriendRequestBase, table=True):
    request_id: Optional[int] = Field(default=None, primary_key=True)

    # Ensure unique friend requests regardless of order
    class Config:
        table_name = "friend_requests"
        sa_column_kwargs = {
            "sender_id,receiver_id": {"unique": True}
        }