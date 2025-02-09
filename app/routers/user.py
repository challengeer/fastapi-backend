from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import hashlib

from ..database import get_session
from ..models.user import User, UserCreate, UserPublic
from ..models.friend_request import FriendRequest, FriendRequestPublic
from ..models.friend import Friend

router = APIRouter(
    prefix="/users"
)

@router.post("/", response_model=User)
def create_user(*, session: Session = Depends(get_session), user: UserCreate):
    db_user = User.model_validate(user)
    db_user.password = hashlib.sha256(db_user.password.encode()).hexdigest()
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.get("/", response_model=list[UserPublic])
def read_users(*, session: Session = Depends(get_session), skip: int = 0, limit: int = 100):
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return users

@router.get("/search", response_model=list[UserPublic])
def read_users(*, session: Session = Depends(get_session), q: str = "", skip: int = 0, limit: int = 20):
    users = session.exec(
        select(User).where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        ).offset(skip).limit(limit)
    ).all()
    return users

@router.get("/{user_id}", response_model=UserPublic)
def read_user(*, session: Session = Depends(get_session), user_id: int):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/{user_id}/requests", response_model=list[FriendRequestPublic])
def read_friend_requests(*, session: Session = Depends(get_session), user_id: int):
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
def read_user_friends(*, session: Session = Depends(get_session), user_id: int):
    statement = (
        select(User)
        .join(Friend, (Friend.user2_id == User.user_id) & (Friend.user1_id == user_id) |
                   (Friend.user1_id == User.user_id) & (Friend.user2_id == user_id))
    )
    friends = session.exec(statement).all()
    return friends