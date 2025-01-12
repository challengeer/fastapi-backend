from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models.user import User
from ..models.friend_request import FriendRequest, FriendRequestPublic, FriendRequestCreate

router = APIRouter(
    prefix="/friend-request"
)

@router.post("/", response_model=FriendRequestPublic)
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