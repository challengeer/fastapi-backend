from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
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
    request_id: Optional[int]
    friendship_status: FriendshipStatus

class SearchUsersResponse(BaseModel):
    friends: list[SearchUser]
    request_sent: list[SearchUser]
    request_received: list[SearchUser]
    none: list[SearchUser]

@router.get("/search", response_model=SearchUsersResponse)
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
            (FriendRequest.receiver_id == User.user_id) & (FriendRequest.sender_id == current_user_id) |
            (FriendRequest.receiver_id == current_user_id) & (FriendRequest.sender_id == User.user_id)
        )
        .where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        )
        .offset(skip)
        .limit(limit)
    )
    
    results = session.exec(statement).all()
    
    categorized_users = {
        "friends": [],
        "request_sent": [],
        "request_received": [],
        "none": []
    }
    
    for user, friendship, request in results:
        if user.user_id == current_user_id:
            continue  # Skip the current user
            
        user_dict = user.model_dump()
        if friendship:
            user_dict["request_id"] = None
            user_dict["friendship_status"] = FriendshipStatus.FRIENDS
            categorized_users["friends"].append(user_dict)
        elif request:
            user_dict["request_id"] = request.request_id
            if request.status == RequestStatus.PENDING:
                if request.sender_id == current_user_id:
                    user_dict["friendship_status"] = FriendshipStatus.REQUEST_SENT
                    categorized_users["request_sent"].append(user_dict)
                else:
                    user_dict["friendship_status"] = FriendshipStatus.REQUEST_RECEIVED
                    categorized_users["request_received"].append(user_dict)
            elif request.status == RequestStatus.REJECTED:
                user_dict["friendship_status"] = FriendshipStatus.NONE
                categorized_users["none"].append(user_dict)
        else:
            user_dict["request_id"] = None
            user_dict["friendship_status"] = FriendshipStatus.NONE
            categorized_users["none"].append(user_dict)
    
    return categorized_users

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
    request_id: Optional[int]
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
            (FriendRequest.receiver_id == User.user_id) & (FriendRequest.sender_id == current_user_id) |
            (FriendRequest.receiver_id == current_user_id) & (FriendRequest.sender_id == user_id)
        )
        .where(User.user_id == user_id)
    )
    
    result = session.exec(statement).first()
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
        
    user, friendship, request = result
    user_dict = user.model_dump()
    
    if friendship:
        user_dict["request_id"] = None
        user_dict["friendship_status"] = FriendshipStatus.FRIENDS
    elif request:
        user_dict["request_id"] = request.request_id
        if request.status == RequestStatus.PENDING:
            user_dict["friendship_status"] = (
                FriendshipStatus.REQUEST_SENT if request.sender_id == current_user_id 
                else FriendshipStatus.REQUEST_RECEIVED
            )
        elif request.status == RequestStatus.REJECTED:
            user_dict["friendship_status"] = FriendshipStatus.NONE
    else:
        user_dict["request_id"] = None
        user_dict["friendship_status"] = FriendshipStatus.NONE
    
    return user_dict