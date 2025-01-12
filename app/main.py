from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session, select
import hashlib

from .database import create_db_and_tables, get_session
from .routers import verification_code
from .models import User, UserCreate, UserPublic, FriendRequest, FriendRequestCreate, FriendRequestPublic

app = FastAPI()

app.include_router(verification_code.router)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.post("/users/", response_model=UserPublic)
def create_user(*, session: Session = Depends(get_session), user: UserCreate):
    db_user = User.model_validate(user)
    db_user.password = hashlib.sha256(db_user.password.encode()).hexdigest()
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


@app.get("/users/")
def read_users(*, session: Session = Depends(get_session), skip: int = 0, limit: int = 100):
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return users


@app.get("/users/{user_id}", response_model=User)
def read_user(*, session: Session = Depends(get_session), user_id: int):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/users/{user_id}/requests", response_model=list[FriendRequestPublic])
def read_friend_requests(*, session: Session = Depends(get_session), user_id: int):
    # Query friend requests received by the user
    statement = select(FriendRequest).where(FriendRequest.receiver_id == user_id)
    friend_requests = session.exec(statement).all()

    # Populate data
    result = []
    for request in friend_requests:
        result.append({
            "request_id": request.request_id,
            "sender": {
                "user_id": request.sender.user_id,
                "username": request.sender.username,
            },
            "status": request.status,
            "sent_at": request.sent_at,
        })
    return result


@app.post("/friend-request/", response_model=FriendRequestPublic)
def create_friend_request(*, session: Session = Depends(get_session), friend_request: FriendRequestCreate):
    # Check if not self
    if friend_request.sender_id == friend_request.receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
    
    # Check if users exist
    sender = session.get(User, friend_request.sender_id)
    receiver = session.get(User, friend_request.receiver_id)
    if not sender or not receiver:
        raise HTTPException(status_code=404, detail="Sender or receiver not found")

    # Check if a friend request already exists
    statement = select(FriendRequest).where(
        (FriendRequest.sender_id == friend_request.sender_id) & 
        (FriendRequest.receiver_id == friend_request.receiver_id)
    )
    existing_request = session.exec(statement).first()
    if existing_request:
        raise HTTPException(status_code=400, detail="Friend request already exists")

    # Create new friend request
    db_friend_request = FriendRequest.model_validate(friend_request)
    session.add(db_friend_request)
    session.commit()
    session.refresh(db_friend_request)
    return db_friend_request