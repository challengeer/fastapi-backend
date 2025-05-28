from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class SubmissionBase(SQLModel):
    challenge_id: int = Field(foreign_key="challenge.challenge_id", index=True)
    user_id: int = Field(foreign_key="user.user_id", index=True)
    photo_url: str = Field(max_length=500)
    caption: Optional[str] = Field(default=None, max_length=500)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Submission(SubmissionBase, table=True):
    submission_id: Optional[int] = Field(default=None, primary_key=True) 