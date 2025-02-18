from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models.user import User
from ..models.friend_request import (
    FriendRequest,
    FriendRequestCreate,
    RequestStatus
)
from ..models.friend import Friend

router = APIRouter(
    prefix="/friend-request",
    tags=["Friend Request"]
)

@router.post("/")
def create_friend_request(*, session: Session = Depends(get_session), friend_request: FriendRequestCreate):
    # Check if not self
    if friend_request.sender_id == friend_request.receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
    
    # Check if users exist
    sender = session.get(User, friend_request.sender_id)
    receiver = session.get(User, friend_request.receiver_id)
    if not sender or not receiver:
        raise HTTPException(status_code=404, detail="Sender or receiver not found")

    # Check if a pending or accepted friend request already exists
    statement = select(FriendRequest).where(
        (FriendRequest.sender_id == friend_request.sender_id) & 
        (FriendRequest.receiver_id == friend_request.receiver_id) &
        (FriendRequest.status != RequestStatus.REJECTED)  # Allow if previous request was rejected
    )
    existing_request = session.exec(statement).first()
    if existing_request:
        raise HTTPException(status_code=400, detail="Active friend request already exists")

    # Create new friend request
    db_friend_request = FriendRequest.model_validate(friend_request)
    session.add(db_friend_request)
    session.commit()
    session.refresh(db_friend_request)
    return db_friend_request

@router.put("/{request_id}/accept")
def accept_friend_request(*, session: Session = Depends(get_session), request_id: int):
    friend_request = session.get(FriendRequest, request_id)
    if not friend_request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if friend_request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Friend request is not pending")
    
    friend_request.status = RequestStatus.ACCEPTED
    
    # Create friendship record
    new_friendship = Friend(
        user1_id=friend_request.sender_id,
        user2_id=friend_request.receiver_id
    )
    session.add(new_friendship)
    
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return friend_request

@router.put("/{request_id}/reject")
def reject_friend_request(*, session: Session = Depends(get_session), request_id: int):
    friend_request = session.get(FriendRequest, request_id)
    if not friend_request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if friend_request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Friend request is not pending")
    
    friend_request.status = RequestStatus.REJECTED
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return friend_request