from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime, timezone

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..models.friend_request import FriendRequest

class UserBase(SQLModel):
    username: str = Field(index=True, unique=True)
    display_name: str = Field(index=True, unique=False)
    email: str = Field(index=True, unique=True)
    phone_number: str = Field(index=True, unique=True)
    password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class User(UserBase, table=True):
    user_id: Optional[int] = Field(default=None, primary_key=True)

    # friend_requests_sent: list["FriendRequest"] = Relationship(
    #     sa_relationship_kwargs={"foreign_keys": "FriendRequest.sender_id"}
    # )
    # friend_requests_received: list["FriendRequest"] = Relationship(
    #     sa_relationship_kwargs={"foreign_keys": "FriendRequest.receiver_id"}
    # )
    # friends: list["Friend"] = Relationship(back_populates="user")

class UserCreate(UserBase):
    pass

class UserPublic(SQLModel):
    user_id: int
    display_name: str
    username: str

class UserUpdate(UserBase):
    pass