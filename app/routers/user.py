from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models.user import User, UserPublic
from ..auth import get_current_user_id

router = APIRouter(
    prefix="/user",
    tags=["User"]
)

@router.get("/{user_id}", response_model=UserPublic)
def read_user(user_id: int, session: Session = Depends(get_session), _: int = Depends(get_current_user_id)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/search", response_model=list[UserPublic])
def search_users(
    q: str = "",
    skip: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: int = Depends(get_current_user_id)
):
    users = session.exec(
        select(User).where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        ).offset(skip).limit(limit)
    ).all()
    return users