from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum

class OverlayType(str, Enum):
    TEXT = "text"

class SubmissionOverlayBase(SQLModel):
    submission_id: int = Field(foreign_key="submission.submission_id", index=True)
    overlay_type: OverlayType = Field(default=OverlayType.TEXT)
    content: str
    x: float
    y: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SubmissionOverlay(SubmissionOverlayBase, table=True):
    overlay_id: Optional[int] = Field(default=None, primary_key=True) 

class SubmissionOverlayCreate(SubmissionOverlayBase):
    overlay_type: OverlayType
    content: str
    x: float
    y: float
