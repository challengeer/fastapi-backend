from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..database import get_session
from ..models.user import User

router = APIRouter(
    prefix="/check-username"
)

@router.get("{username}", response_model=bool)
def check_username_exists(*, session: Session = Depends(get_session), username: str):
    statement = select(User).where(User.username == username)
    existing_user = session.exec(statement).first()
    return existing_user is not None