import firebase_admin
from firebase_admin import credentials, messaging
from typing import List, Optional

from app.config import FIREBASE_CREDENTIALS_JSON

class FirebaseNotificationService:
    def __init__(self):
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_JSON)
        firebase_admin.initialize_app(cred)
    
    async def send_push_notification(
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
            
            response = messaging.send(message)
            print(f'Successfully sent message: {response}')
            return True
            
        except Exception as e:
            print(f'Error sending message: {e}')
            return False
    
    async def send_multicast_notification(
        self,
        fcm_tokens: List[str],
        title: str,
        body: str,
        data: Optional[dict] = None
    ) -> dict:
        try:
            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=data or {},
                tokens=fcm_tokens,
            )
            
            response = messaging.send_multicast(message)
            print(f'Successfully sent message to {response.success_count} devices')
            return {
                'success_count': response.success_count,
                'failure_count': response.failure_count
            }
            
        except Exception as e:
            print(f'Error sending message: {e}')
            return {'success_count': 0, 'failure_count': len(fcm_tokens)} 