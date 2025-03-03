from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum

class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"

class ChallengeInvitationBase(SQLModel):
    challenge_id: int = Field(foreign_key="challenge.challenge_id", index=True)
    sender_id: int = Field(foreign_key="user.user_id", index=True)
    receiver_id: int = Field(foreign_key="user.user_id", index=True)
    status: InvitationStatus = Field(default=InvitationStatus.PENDING)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    responded_at: Optional[datetime] = None

class ChallengeInvitation(ChallengeInvitationBase, table=True):
    invitation_id: Optional[int] = Field(default=None, primary_key=True)

    class Config:
        sa_column_kwargs = {
            "challenge_id,receiver_id": {"unique": True}  # One invitation per user per challenge
        }