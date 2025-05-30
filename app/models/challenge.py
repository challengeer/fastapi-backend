from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class ChallengeBase(SQLModel):
    creator_id: int = Field(foreign_key="user.user_id", index=True)
    title: str = Field(max_length=200)
    description: Optional[str] = Field(max_length=1000)
    emoji: str = Field(max_length=10)
    category: str = Field(max_length=100)
    start_date: datetime
    end_date: datetime
    duration: Optional[int] = 30  # How long users should spend doing the activity (in minutes)
    lifetime: Optional[int] = 48  # How long the challenge is open (in hours)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Challenge(ChallengeBase, table=True):
    challenge_id: Optional[int] = Field(default=None, primary_key=True)

class ChallengePublic(ChallengeBase):
    pass