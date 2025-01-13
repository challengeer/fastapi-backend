from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import hashlib

from ..database import get_session
from ..models.user import User, UserCreate
from ..models.friend_request import FriendRequest, FriendRequestPublic

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


@router.get("/")
def read_users(*, session: Session = Depends(get_session), skip: int = 0, limit: int = 100):
    users = session.exec(select(User).offset(skip).limit(limit)).all()
    return users


@router.get("/{user_id}", response_model=User)
def read_user(*, session: Session = Depends(get_session), user_id: int):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/{user_id}/requests")
def read_friend_requests(*, session: Session = Depends(get_session), user_id: int):
    # user = session.get(User, user_id)
    # print(user.friend_requests_sent)

    # Query friend requests received by the user
    statement = select(FriendRequest, User).join(User)
    friend_requests = session.exec(statement)

    result = []
    for request, user in friend_requests:
        result.append({
            "username": user.username,
            "sent_at": request.sent_at
        })

    # Populate data
    # result = []
    # for request in friend_requests:
        # result.append({
        #     "request_id": request.request_id,
        #     # "sender": {
        #     #     "user_id": request.sender.user_id,
        #     #     "username": request.sender.username,
        #     # },
        #     "status": request.status,
        #     "sent_at": request.sent_at,
        # })
        # print(FriendRequest.model_validate(request))

    return result