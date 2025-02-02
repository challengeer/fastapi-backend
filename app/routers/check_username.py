from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from pydantic import BaseModel

from ..database import get_session
from ..models.user import User

router = APIRouter(
    prefix="/check-username"
)

class UsernameCheckResponse(BaseModel):
    username: str
    exists: bool

@router.get("/{username}", response_model=UsernameCheckResponse)
def check_username_exists(*, session: Session = Depends(get_session), username: str):
    statement = select(User).where(User.username == username)
    existing_user = session.exec(statement).first()
    return UsernameCheckResponse(
        username=username,
        exists=existing_user is not None
    )