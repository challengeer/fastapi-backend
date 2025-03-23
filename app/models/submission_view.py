from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class SubmissionViewBase(SQLModel):
    submission_id: int = Field(foreign_key="challengesubmission.submission_id", index=True)
    viewer_id: int = Field(foreign_key="user.user_id", index=True)
    viewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SubmissionView(SubmissionViewBase, table=True):
    view_id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        sa_column_kwargs = {
            "submission_id,viewer_id": {"unique": True}  # Track each submission view once per user
        }