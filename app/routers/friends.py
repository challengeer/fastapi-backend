from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel

from ..database import get_session
from ..models.user import User, UserPublic
from ..models.friend_request import FriendRequest, FriendRequestPublic, RequestStatus
from ..models.friendship import Friendship
from ..auth import get_current_user_id

router = APIRouter(
    prefix="/friends",
    tags=["Friends"]
)

class FriendRequestCreate(BaseModel):
    receiver_id: int

class FriendRequestAction(BaseModel):
    request_id: int

@router.post("/add")
def create_friend_request(
    request: FriendRequestCreate,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    # Check if not self
    if user_id == request.receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
    
    # Check if user exists
    receiver = session.get(User, request.receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    # Check if a pending or accepted friend request already exists
    statement = select(FriendRequest).where(
        (FriendRequest.sender_id == user_id) & 
        (FriendRequest.receiver_id == request.receiver_id) &
        (FriendRequest.status != RequestStatus.REJECTED)  # Allow if previous request was rejected
    )
    existing_request = session.exec(statement).first()
    if existing_request:
        raise HTTPException(status_code=400, detail="Active friend request already exists")

    # Create new friend request
    friend_request = FriendRequest(
        sender_id=user_id,
        receiver_id=request.receiver_id,
        status=RequestStatus.PENDING
    )
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return friend_request

@router.put("/accept")
def accept_friend_request(
    request: FriendRequestAction,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    friend_request = session.get(FriendRequest, request.request_id)
    if not friend_request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if friend_request.receiver_id != user_id:
        raise HTTPException(status_code=403, detail="Can only accept your own friend requests")
    
    if friend_request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Friend request is not pending")
    
    friend_request.status = RequestStatus.ACCEPTED
    
    # Create friendship record
    new_friendship = Friendship(
        user1_id=friend_request.sender_id,
        user2_id=friend_request.receiver_id
    )
    session.add(new_friendship)
    
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return friend_request

@router.put("/reject")
def reject_friend_request(
    request: FriendRequestAction,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    friend_request = session.get(FriendRequest, request.request_id)
    if not friend_request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if friend_request.receiver_id != user_id:
        raise HTTPException(status_code=403, detail="Can only reject your own friend requests")
    
    if friend_request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Friend request is not pending")
    
    friend_request.status = RequestStatus.REJECTED
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return friend_request

@router.get("/list", response_model=list[UserPublic])
def get_friends(session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    statement = (
        select(User)
        .join(Friendship, (Friendship.user2_id == User.user_id) & (Friendship.user1_id == user_id) |
                   (Friendship.user1_id == User.user_id) & (Friendship.user2_id == user_id))
    )
    
    friends = session.exec(statement).all()
    return friends

@router.get("/requests", response_model=list[FriendRequestPublic])
def get_friend_requests(session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    statement = (
        select(User, FriendRequest)
            .join(FriendRequest, FriendRequest.sender_id == User.user_id)
            .where(FriendRequest.receiver_id == user_id)
    )
    results = session.exec(statement).all()

    friend_requests = []
    for user, request in results:
        friend_requests.append(FriendRequestPublic(
            request_id=request.request_id,
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            profile_picture=user.profile_picture,
            status=request.status
        ))

    return friend_requests