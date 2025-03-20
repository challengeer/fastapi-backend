import sys
import os
import uuid

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, create_engine
from datetime import datetime, timedelta, timezone
import random
import hashlib
from app.models.user import User
from app.models.friend_request import FriendRequest, RequestStatus
from app.models.friendship import Friendship

from app.config import DATABASE_URL, S3_BUCKET_NAME, S3_URL
from app.services.database import create_db_and_tables
from app.services.s3 import s3_client

engine = create_engine(DATABASE_URL)

# Test data
test_users = [
    {"username": "john_doe", "display_name": "John Doe", "email": "john@example.com", "phone_number": "+1234567890", "profile_picture": "scripts/images/thispersondoesnotexist.jpg"},
    {"username": "jane_smith", "display_name": "Jane Smith", "email": "jane@example.com", "phone_number": "+1234567891", "profile_picture": "scripts/images/thispersondoesnotexist4.jpg"},
    {"username": "bob_wilson", "display_name": "Bob Wilson", "email": "bob@example.com", "phone_number": "+1234567892"},
    {"username": "alice_jones", "display_name": "Alice Jones", "email": "alice@example.com", "phone_number": "+1234567893"},
    {"username": "charlie_brown", "display_name": "Charlie Brown", "email": "charlie@example.com", "phone_number": "+1234567894"},
    {"username": "emma_davis", "display_name": "Emma Davis", "email": "emma@example.com", "phone_number": "+1234567895"},
    {"username": "david_miller", "display_name": "David Miller", "email": "david@example.com", "phone_number": "+1234567896", "profile_picture": "scripts/images/thispersondoesnotexist1.jpg"},
    {"username": "sophia_wilson", "display_name": "Sophia Wilson", "email": "sophia@example.com", "phone_number": "+1234567897", "profile_picture": "scripts/images/thispersondoesnotexist2.jpg"},
    {"username": "james_taylor", "display_name": "James Taylor", "email": "james@example.com", "phone_number": "+1234567898", "profile_picture": ""},
    {"username": "olivia_brown", "display_name": "Olivia Brown", "email": "olivia@example.com", "phone_number": "+1234567899", "profile_picture": "scripts/images/thispersondoesnotexist5.jpg"},
]

def create_users(session: Session):
    users = []
    # Get the absolute path to the project root directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    for user_data in test_users:
        if "profile_picture" in user_data and user_data["profile_picture"]:
            image_path = os.path.join(base_dir, user_data["profile_picture"])
            print(f"Looking for image at: {image_path}")  # Debug print
            
            # Only proceed if the file exists
            if os.path.exists(image_path):
                new_filename = f"profile-pictures/{uuid.uuid4()}.jpg"
                try:
                    s3_client.upload_file(
                        image_path,
                        S3_BUCKET_NAME,
                        new_filename
                    )
                    s3_url = f"{S3_URL}/{new_filename}"
                    user_data["profile_picture"] = s3_url
                    print(f"Successfully uploaded profile picture to {s3_url}")
                except Exception as e:
                    print(f"Failed to upload profile picture for {user_data['username']}: {str(e)}")
                    user_data["profile_picture"] = None
            else:
                print(f"❌ Profile picture not found for {user_data['username']}: {image_path}")
                user_data["profile_picture"] = None

        user = User(
            username=user_data["username"],
            display_name=user_data["display_name"],
            email=user_data["email"],
            phone_number=user_data["phone_number"],
            profile_picture=user_data["profile_picture"] if "profile_picture" in user_data else None,
            password=hashlib.sha256("password123".encode()).hexdigest()  # Same password for all test users
        )
        users.append(user)
    
    session.add_all(users)
    session.commit()
    return users

def create_friend_requests(session: Session, users: list[User]):
    # Create some random friend requests
    for _ in range(15):  # Create 15 random friend requests
        sender = random.choice(users)
        receiver = random.choice(users)
        
        # Avoid self-friend requests by comparing user_ids
        while sender.user_id == receiver.user_id:
            receiver = random.choice(users)
            
        # Random status
        status = random.choice([RequestStatus.PENDING, RequestStatus.ACCEPTED, RequestStatus.REJECTED])
        
        # Random sent_at time within the last 30 days
        sent_at = datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))
        
        friend_request = FriendRequest(
            sender_id=sender.user_id,
            receiver_id=receiver.user_id,
            status=status,
            sent_at=sent_at
        )
        session.add(friend_request)
    
    session.commit()

def create_friendships(session: Session, users: list[User]):
    # Create some random friendships
    for _ in range(10):  # Create 10 random friendships
        user1 = random.choice(users)
        user2 = random.choice(users)
        
        # Avoid self-friendships by comparing user_ids
        while user1.user_id == user2.user_id:
            user2 = random.choice(users)
            
        # Random friendship creation date within the last 60 days
        since = datetime.now(timezone.utc) - timedelta(days=random.randint(0, 60))
        
        friendship = Friendship(
            user1_id=user1.user_id,
            user2_id=user2.user_id,
            since=since
        )
        session.add(friendship)
    
    session.commit()

def main():
    create_db_and_tables()

    with Session(engine) as session:
        # Create users
        users = create_users(session)
        print(f"Created {len(users)} users")
        
        # Create friend requests
        create_friend_requests(session, users)
        print("Created friend requests")
        
        # Create friendships
        create_friendships(session, users)
        print("Created friendships")

if __name__ == "__main__":
    main() 