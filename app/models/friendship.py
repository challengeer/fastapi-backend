from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class FriendshipBase(SQLModel):
    user1_id: int = Field(foreign_key="user.user_id", index=True)
    user2_id: int = Field(foreign_key="user.user_id", index=True)
    since: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Friendship(FriendshipBase, table=True):
    friendship_id: Optional[int] = Field(default=None, primary_key=True)

    # Ensure unique friendships regardless of order
    class Config:
        table_name = "friendships"
        sa_column_kwargs = {
            "user1_id,user2_id": {"unique": True}
        }