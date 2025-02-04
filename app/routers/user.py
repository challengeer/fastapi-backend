from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import hashlib

from ..database import get_session
from ..models.user import User, UserCreate, UserPublic
from ..models.friend_request import FriendRequest, FriendRequestPublic, RequestStatus
from ..models.friend import Friend
from ..s3 import s3_client
from ..config import S3_BUCKET_NAME  # Make sure to add this to your config

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

def get_profile_picture_url(key: str | None) -> str | None:
    if not key:
        return None
    
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': S3_BUCKET_NAME,
            'Key': key
        },
        ExpiresIn=3600  # URL valid for 1 hour
    )
    return url

@router.get("/", response_model=list[UserPublic])
def read_users(*, session: Session = Depends(get_session), skip: int = 0, limit: int = 100):
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    for user in users:
        user.profile_picture = get_profile_picture_url(user.profile_picture)
    return users

@router.get("/search", response_model=list[UserPublic])
def read_users(*, session: Session = Depends(get_session), q: str = "", skip: int = 0, limit: int = 20):
    users = session.exec(
        select(User).where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        ).offset(skip).limit(limit)
    ).all()
    for user in users:
        user.profile_picture = get_profile_picture_url(user.profile_picture)
    return users

@router.get("/{user_id}", response_model=UserPublic)
def read_user(*, session: Session = Depends(get_session), user_id: int):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.profile_picture = get_profile_picture_url(user.profile_picture)
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
    
    for friend in friends:
        friend.profile_picture = get_profile_picture_url(friend.profile_picture)
    return friends