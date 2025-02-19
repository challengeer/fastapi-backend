from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import hashlib

from ..database import get_session
from ..models.user import User, UserCreate, UserPublic
from ..models.friend_request import FriendRequest, FriendRequestPublic
from ..models.friend import Friend
from ..auth import get_current_user_id

router = APIRouter(
    prefix="/users",
    tags=["User"]
)

@router.post("/", response_model=User)
def create_user(*, session: Session = Depends(get_session), user: UserCreate):
    # This endpoint remains public for user registration
    db_user = User.model_validate(user)
    db_user.password = hashlib.sha256(db_user.password.encode()).hexdigest()
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.get("/", response_model=list[UserPublic])
def read_users(
    *,
    session: Session = Depends(get_session),
    _: int = Depends(get_current_user_id),  # Require authentication
    skip: int = 0,
    limit: int = 100
):
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return users

@router.get("/search", response_model=list[UserPublic])
def search_users(
    *,
    session: Session = Depends(get_session),
    _: int = Depends(get_current_user_id),  # Require authentication
    q: str = "",
    skip: int = 0,
    limit: int = 20
):
    users = session.exec(
        select(User).where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        ).offset(skip).limit(limit)
    ).all()
    return users

@router.get("/{user_id}", response_model=UserPublic)
def read_user(
    *,
    session: Session = Depends(get_session),
    _: int = Depends(get_current_user_id),  # Add authentication
    user_id: int
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/{user_id}/requests", response_model=list[FriendRequestPublic])
def read_friend_requests(
    *,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
    user_id: int
):
    # Verify user is accessing their own requests
    if current_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Can only access your own friend requests"
        )
    
    statement = (
        select(User, FriendRequest)
            .join(FriendRequest, FriendRequest.sender_id == User.user_id)
            .where(FriendRequest.receiver_id == user_id)
    )
    results = session.exec(statement).all()
    
    friend_requests = []
    for user, request in results:
        friend_requests.append(FriendRequestPublic(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            profile_picture=user.profile_picture,
            status=request.status
        ))

    return friend_requests

@router.get("/{user_id}/friends", response_model=list[UserPublic])
def read_user_friends(
    *,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id),
    user_id: int
):
    # Verify user is accessing their own friends or is friends with the requested user
    if current_user_id != user_id:
        # Check if they are friends
        friendship = session.exec(
            select(Friend).where(
                ((Friend.user1_id == current_user_id) & (Friend.user2_id == user_id)) |
                ((Friend.user2_id == current_user_id) & (Friend.user1_id == user_id))
            )
        ).first()
        if not friendship:
            raise HTTPException(
                status_code=403,
                detail="Can only view friends list of yourself or your friends"
            )

    statement = (
        select(User)
        .join(Friend, (Friend.user2_id == User.user_id) & (Friend.user1_id == user_id) |
                   (Friend.user1_id == User.user_id) & (Friend.user2_id == user_id))
    )
    friends = session.exec(statement).all()
    return friends