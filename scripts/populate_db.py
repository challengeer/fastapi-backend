import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, create_engine
from datetime import datetime, timedelta, timezone
import random
import hashlib
from app.models.user import User
from app.models.friend_request import FriendRequest, RequestStatus
from app.models.friend import Friend

from app.config import DATABASE_URL
from app.database import create_db_and_tables
engine = create_engine(DATABASE_URL)

# Test data
test_users = [
    {"username": "john_doe", "display_name": "John Doe", "email": "john@example.com", "phone_number": "+1234567890"},
    {"username": "jane_smith", "display_name": "Jane Smith", "email": "jane@example.com", "phone_number": "+1234567891"},
    {"username": "bob_wilson", "display_name": "Bob Wilson", "email": "bob@example.com", "phone_number": "+1234567892"},
    {"username": "alice_jones", "display_name": "Alice Jones", "email": "alice@example.com", "phone_number": "+1234567893"},
    {"username": "charlie_brown", "display_name": "Charlie Brown", "email": "charlie@example.com", "phone_number": "+1234567894"},
    {"username": "emma_davis", "display_name": "Emma Davis", "email": "emma@example.com", "phone_number": "+1234567895"},
    {"username": "david_miller", "display_name": "David Miller", "email": "david@example.com", "phone_number": "+1234567896"},
    {"username": "sophia_wilson", "display_name": "Sophia Wilson", "email": "sophia@example.com", "phone_number": "+1234567897"},
    {"username": "james_taylor", "display_name": "James Taylor", "email": "james@example.com", "phone_number": "+1234567898"},
    {"username": "olivia_brown", "display_name": "Olivia Brown", "email": "olivia@example.com", "phone_number": "+1234567899"},
]

def create_users(session: Session):
    users = []
    for user_data in test_users:
        user = User(
            username=user_data["username"],
            display_name=user_data["display_name"],
            email=user_data["email"],
            phone_number=user_data["phone_number"],
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
        
        friendship = Friend(
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