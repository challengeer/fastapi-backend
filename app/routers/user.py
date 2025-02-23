from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional
from enum import Enum

from ..database import get_session
from ..models.user import User, UserPublic
from ..models.friendship import Friendship
from ..models.friend_request import FriendRequest, RequestStatus
from ..auth import get_current_user_id

router = APIRouter(
    prefix="/user",
    tags=["User"]
)

class FriendshipStatus(str, Enum):
    FRIENDS = "friends"
    REQUEST_SENT = "request_sent"
    REQUEST_RECEIVED = "request_received"
    NONE = "none"

class SearchUser(UserPublic):
    friendship_status: FriendshipStatus

@router.get("/search", response_model=list[SearchUser])
def search_users(
    q: str = "",
    skip: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    statement = (
        select(User, Friendship, FriendRequest)
        .outerjoin(
            Friendship,
            ((Friendship.user1_id == User.user_id) & (Friendship.user2_id == current_user_id)) |
            ((Friendship.user2_id == User.user_id) & (Friendship.user1_id == current_user_id))
        )
        .outerjoin(
            FriendRequest,
            (FriendRequest.receiver_id == User.user_id) & (FriendRequest.sender_id == current_user_id)
        )
        .where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        )
        .offset(skip)
        .limit(limit)
    )
    
    results = session.exec(statement).all()
    
    users = []
    for user, friendship, request in results:
        if user.user_id == current_user_id:
            continue  # Skip the current user
            
        user_dict = user.model_dump()
        if friendship:
            user_dict["friendship_status"] = FriendshipStatus.FRIENDS
        elif request:
            if request.status == RequestStatus.PENDING:
                user_dict["friendship_status"] = (
                    FriendshipStatus.REQUEST_SENT if request.sender_id == current_user_id 
                    else FriendshipStatus.REQUEST_RECEIVED
                )
            elif request.status == RequestStatus.REJECTED:
                user_dict["friendship_status"] = FriendshipStatus.NONE  # Treat rejected same as no relationship
        else:
            user_dict["friendship_status"] = FriendshipStatus.NONE
            
        users.append(user_dict)
    
    return users

class UserLocal(UserPublic):
    email: Optional[str]
    phone_number: Optional[str]

@router.get("/me", response_model=UserLocal)
def read_current_user(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    user = session.exec(select(User).where(User.user_id == current_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

class UserProfile(UserPublic):
    friendship_status: FriendshipStatus
    
@router.get("/{user_id}", response_model=UserProfile)
def read_user(
    user_id: int, 
    session: Session = Depends(get_session), 
    current_user_id: int = Depends(get_current_user_id)
):
    statement = (
        select(User, Friendship, FriendRequest)
        .outerjoin(
            Friendship,
            ((Friendship.user1_id == User.user_id) & (Friendship.user2_id == current_user_id)) |
            ((Friendship.user2_id == User.user_id) & (Friendship.user1_id == current_user_id))
        )
        .outerjoin(
            FriendRequest,
            (FriendRequest.receiver_id == User.user_id) & (FriendRequest.sender_id == current_user_id)
        )
        .where(User.user_id == user_id)
    )
    
    result = session.exec(statement).first()
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
        
    user, friendship, request = result
    user_dict = user.model_dump()
    
    if friendship:
        user_dict["friendship_status"] = FriendshipStatus.FRIENDS
    elif request:
        if request.status == RequestStatus.PENDING:
            user_dict["friendship_status"] = (
                FriendshipStatus.REQUEST_SENT if request.sender_id == current_user_id 
                else FriendshipStatus.REQUEST_RECEIVED
            )
        elif request.status == RequestStatus.REJECTED:
            user_dict["friendship_status"] = FriendshipStatus.NONE  # Treat rejected same as no relationship
    else:
        user_dict["friendship_status"] = FriendshipStatus.NONE
    
    return user_dict