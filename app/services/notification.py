import firebase_admin
from firebase_admin import credentials, messaging
from typing import Optional, List
from enum import Enum
from sqlmodel import Session, select

from app.config import FIREBASE_CREDENTIALS_JSON
from app.models.device import Device

class NotificationType(str, Enum):
    CHALLENGE_INVITE = "challenge_invite"
    CHALLENGE_SUBMISSION = "challenge_submission"
    CHALLENGE_ENDING = "challenge_ending"
    FRIEND_REQUEST = "friend_request"
    FRIEND_ACCEPT = "friend_accept"

class NotificationService:
    def __init__(self):
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_JSON)
        
        # Initialize Firebase Admin SDK if not already initialized
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(cred)

    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: Optional[dict] = None
    ) -> bool:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=data or {},
                token=fcm_token,
            )
            
            messaging.send(message)
            return True
        except Exception as e:
            print(f"Error sending notification: {e}")
            return False

    async def send_notification_to_user(
        self,
        db: Session,
        user_id: int,
        title: str,
        body: str,
        data: Optional[dict] = None
    ) -> List[bool]:
        # Get all devices for the user
        devices = db.exec(
            select(Device)
            .where(Device.user_id == user_id)
            .where(Device.fcm_token.is_not(None))  # Only get devices with FCM tokens
        ).all()
        
        # Send notification to all devices
        results = []
        for device in devices:
            success = await self.send_notification(
                fcm_token=device.fcm_token,
                title=title,
                body=body,
                data=data
            )
            results.append(success)
        
        return results

    async def send_challenge_invite(
        self,
        db: Session,
        user_id: int,
        sender_name: str,
        challenge_title: str,
        challenge_id: int,
        invitation_id: int
    ):
        return await self.send_notification_to_user(
            db=db,
            user_id=user_id,
            title="New Challenge Invitation!",
            body=f"{sender_name} invited you to '{challenge_title}'",
            data={
                "type": NotificationType.CHALLENGE_INVITE,
                "challenge_id": str(challenge_id),
                "invitation_id": str(invitation_id)
            }
        )

    async def send_challenge_submission(
        self,
        fcm_token: str,
        submitter_name: str,
        challenge_title: str,
        challenge_id: int
    ):
        return await self.send_notification(
            fcm_token=fcm_token,
            title="New Challenge Submission!",
            body=f"{submitter_name} submitted to '{challenge_title}'",
            data={
                "type": NotificationType.CHALLENGE_SUBMISSION,
                "challenge_id": str(challenge_id)
            }
        )

    async def send_challenge_ending(
        self,
        fcm_token: str,
        challenge_title: str,
        challenge_id: int,
        hours_left: int
    ):
        return await self.send_notification(
            fcm_token=fcm_token,
            title="Challenge Ending Soon!",
            body=f"'{challenge_title}' ends in {hours_left} hours",
            data={
                "type": NotificationType.CHALLENGE_ENDING,
                "challenge_id": str(challenge_id)
            }
        )

    async def send_friend_request(
        self,
        fcm_token: str,
        sender_name: str,
        sender_id: int
    ):
        return await self.send_notification(
            fcm_token=fcm_token,
            title="New Friend Request",
            body=f"{sender_name} sent you a friend request",
            data={
                "type": NotificationType.FRIEND_REQUEST,
                "sender_id": str(sender_id)
            }
        )

    async def send_friend_accept(
        self,
        fcm_token: str,
        accepter_name: str,
        accepter_id: int
    ):
        return await self.send_notification(
            fcm_token=fcm_token,
            title="Friend Request Accepted",
            body=f"{accepter_name} accepted your friend request",
            data={
                "type": NotificationType.FRIEND_ACCEPT,
                "user_id": str(accepter_id)
            }
        ) 