from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime, timezone
from enum import Enum

class RequestStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

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

class UserBase(SQLModel):
    username: str = Field(index=True, unique=True)
    display_name: str | None = None
    email: str = Field(index=True, unique=True)
    phone_number: str = Field(index=True, unique=True)
    password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class User(UserBase, table=True):
    user_id: int | None = Field(default=None, primary_key=True)

    friend_requests_sent: list["FriendRequest"] = Relationship(
        back_populates="sender", sa_relationship_kwargs={"foreign_keys": "FriendRequest.sender_id"}
    )
    friend_requests_received: list["FriendRequest"] = Relationship(
        back_populates="receiver", sa_relationship_kwargs={"foreign_keys": "FriendRequest.receiver_id"}
    )
    # friends: list["Friend"] = Relationship(back_populates="user")

class UserCreate(UserBase):
    pass

class UserPublic(SQLModel):
    user_id: int
    username: str

class UserUpdate(UserBase):
    pass

class FriendBase(SQLModel):
    user1_id: int = Field(foreign_key="user.user_id")
    user2_id: int = Field(foreign_key="user.user_id")
    since: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Friend(FriendBase, table=True):
    friendship_id: int | None = Field(default=None, primary_key=True)

    # user: User = Relationship(back_populates="friends")

class FriendCreate(FriendBase):
    pass

class FriendPublic(FriendBase):
    friendship_id: int

class FriendUpdate(FriendBase):
    pass

class FriendRequestBase(SQLModel):
    sender_id: int = Field(foreign_key="user.user_id")
    receiver_id: int = Field(foreign_key="user.user_id")
    status: RequestStatus = Field(default=RequestStatus.PENDING)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FriendRequest(FriendRequestBase, table=True):
    request_id: int | None = Field(default=None, primary_key=True)

    sender: User = Relationship(
        back_populates="friend_requests_sent", sa_relationship_kwargs={"foreign_keys": "FriendRequest.sender_id"}
    )
    receiver: User = Relationship(
        back_populates="friend_requests_received", sa_relationship_kwargs={"foreign_keys": "FriendRequest.receiver_id"}
    )

class FriendRequestCreate(FriendRequestBase):
    pass

class FriendRequestPublic(SQLModel):
    request_id: int
    sender: UserPublic
    status: RequestStatus
    sent_at: datetime


class FriendRequestUpdate(FriendRequestBase):
    pass


