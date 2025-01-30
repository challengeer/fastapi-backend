from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class FriendBase(SQLModel):
    user1_id: int = Field(foreign_key="user.user_id")
    user2_id: int = Field(foreign_key="user.user_id")
    since: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Friend(FriendBase, table=True):
    friendship_id: Optional[int] = Field(default=None, primary_key=True)

    # user: User = Relationship(back_populates="friends")

class FriendCreate(FriendBase):
    pass

class FriendPublic(FriendBase):
    friendship_id: int

class FriendUpdate(FriendBase):
    pass