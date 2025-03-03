from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class ChallengeSubmissionBase(SQLModel):
    challenge_id: int = Field(foreign_key="challenges.challenge_id", index=True)
    user_id: int = Field(foreign_key="user.user_id", index=True)
    photo_url: str = Field(max_length=500)
    caption: Optional[str] = Field(default=None, max_length=500)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ChallengeSubmission(ChallengeSubmissionBase, table=True):
    submission_id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        table_name = "challenge_submissions"
        sa_column_kwargs = {
            "challenge_id,user_id": {"unique": True}  # One submission per user per challenge
        } 