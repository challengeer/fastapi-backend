from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum

class ChallengeStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class ChallengeBase(SQLModel):
    creator_id: int = Field(foreign_key="user.user_id", index=True)
    title: str = Field(max_length=200)
    description: str = Field(max_length=1000)
    start_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_date: Optional[datetime] = None
    status: ChallengeStatus = Field(default=ChallengeStatus.ACTIVE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Challenge(ChallengeBase, table=True):
    challenge_id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        table_name = "challenges" 