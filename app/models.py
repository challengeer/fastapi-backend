from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime, timezone
from enum import Enum

class RequestStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    secret_name: str
    age: int | None = Field(default=None, index=True)

class UserBase(SQLModel):
    username: str = Field(index=True, unique=True)
    display_name: str | None = None
    email: str = Field(index=True, unique=True)
    phone_number: str = Field(index=True, unique=True)
    password: str
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    # sent_requests: list["FriendRequest"] = Relationship(back_populates="sender")
    # received_requests: list["FriendRequest"] = Relationship(back_populates="receiver")
    # friends: list["Friend"] = Relationship(back_populates="user")

class User(UserBase, table=True):
    user_id: int | None = Field(default=None, primary_key=True)

class UserCreate(UserBase):
    pass

class UserUpdate(UserBase):
    pass

# class Friend(SQLModel, table=True):
#     friendship_id: int | None = Field(default=None, primary_key=True)
#     user1_id: int = Field(foreign_key="user.user_id")
#     user2_id: int = Field(foreign_key="user.user_id")
#     since: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

#     # Relationships
#     user: User = Relationship(back_populates="friends")

# class FriendRequest(SQLModel, table=True):
#     request_id: int | None = Field(default=None, primary_key=True)
#     sender_id: int = Field(foreign_key="user.user_id")
#     receiver_id: int = Field(foreign_key="user.user_id")
#     status: RequestStatus = Field(default=RequestStatus.PENDING)
#     sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

#     # Relationships
#     sender: User = Relationship(back_populates="sent_requests")
#     receiver: User = Relationship(back_populates="received_requests")
