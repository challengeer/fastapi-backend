from fastapi import BackgroundTasks
from sqlmodel import Session, select
from datetime import datetime, timedelta

from ..models.challenge import Challenge, ChallengeStatus
from ..models.challenge_invitation import ChallengeInvitation, InvitationStatus
from ..models.user import User
from ..services.notification import NotificationService

async def send_ending_soon_notifications(session: Session):
    """Send notifications for challenges ending in 6 hours"""
    notification_service = NotificationService()
    
    # Find challenges ending in ~6 hours
    end_time = datetime.now() + timedelta(hours=6)
    soon_ending = session.exec(
        select(Challenge)
        .where(
            (Challenge.status == ChallengeStatus.ACTIVE) &
            (Challenge.end_date <= end_time) &
            (Challenge.end_date > datetime.now())
        )
    ).all()

    for challenge in soon_ending:
        # Get all participants including creator
        participants = session.exec(
            select(User)
            .where(
                (User.user_id == challenge.creator_id) |
                User.user_id.in_(
                    select(ChallengeInvitation.receiver_id)
                    .where(
                        (ChallengeInvitation.challenge_id == challenge.challenge_id) &
                        (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
                    )
                )
            )
        ).all()

        hours_left = int((challenge.end_date - datetime.now()).total_seconds() / 3600)

        # Send notifications to all participants
        for participant in participants:
            if participant.fcm_token:
                await notification_service.send_challenge_ending(
                    fcm_token=participant.fcm_token,
                    challenge_title=challenge.title,
                    challenge_id=challenge.challenge_id,
                    hours_left=hours_left
                ) 