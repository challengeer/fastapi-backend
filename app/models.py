from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
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

class User(SQLModel, table=True):
    user_id: int | None = Field(default=None, primary_key=True)
    display_name: str
    username: str
    email: str
    phone_number: str
    password: bytes
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    sent_requests: list["FriendRequest"] = Relationship(back_populates="sender")
    received_requests: list["FriendRequest"] = Relationship(back_populates="receiver")
    friends: list["Friend"] = Relationship(back_populates="user")

class Friend(SQLModel, table=True):
    friendship_id: int | None = Field(default=None, primary_key=True)
    user1_id: int = Field(foreign_key="user.user_id")
    user2_id: int = Field(foreign_key="user.user_id")
    since: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    user: User = Relationship(back_populates="friends")

class FriendRequest(SQLModel, table=True):
    request_id: int | None = Field(default=None, primary_key=True)
    sender_id: int = Field(foreign_key="user.user_id")
    receiver_id: int = Field(foreign_key="user.user_id")
    status: RequestStatus = Field(default=RequestStatus.PENDING)
    sent_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    sender: User = Relationship(back_populates="sent_requests")
    receiver: User = Relationship(back_populates="received_requests")
