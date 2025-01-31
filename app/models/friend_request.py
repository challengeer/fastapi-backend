from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime, timezone
from enum import Enum

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..models.user import UserPublic

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

    # sender: "User" = Relationship(
    #     back_populates="friend_requests_sent", sa_relationship_kwargs={"foreign_keys": "FriendRequest.sender_id"}
    # )
    # receiver: "User" = Relationship(
    #     back_populates="friend_requests_received", sa_relationship_kwargs={"foreign_keys": "FriendRequest.receiver_id"}
    # )

class FriendRequestCreate(SQLModel):
    sender_id: int
    receiver_id: int

class FriendRequestPublic(SQLModel):
    user_id: int
    username: str
    display_name: str
    status: RequestStatus

class FriendRequestUpdate(FriendRequestBase):
    pass