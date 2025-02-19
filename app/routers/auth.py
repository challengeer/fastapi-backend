from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from datetime import timedelta
from jose import jwt
from google.oauth2 import id_token
from google.auth.transport import requests

from ..auth import create_token
from ..database import get_session
from ..models.user import User, UserPublic
from ..config import GOOGLE_CLIENT_ID, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

def create_tokens(user_id: int):
    access_token = create_token(
        data={"sub": str(user_id), "type": "access"},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_token(
        data={"sub": str(user_id), "type": "refresh"},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return {"access_token": access_token, "refresh_token": refresh_token}

@router.post("/google")
async def google_auth(token: str, db: Session = Depends(get_session)):
    try:
        idinfo = id_token.verify_oauth2_token(
            token, requests.Request(), GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )

        user = db.exec(
            select(User).where(
                (User.google_id == idinfo["sub"]) |
                (User.google_email == idinfo["email"]) |
                (User.phone_number == idinfo.get("phoneNumber"))
            )
        ).first()

        if not user:
            # Create new user
            user = User(
                username=f"google_{idinfo['sub']}",
                display_name=idinfo.get("name", ""),
                profile_picture=idinfo.get("picture"),
                email=idinfo["email"],
                phone_number=idinfo.get("phoneNumber", ""),  # This might be None from Google
                google_id=idinfo["sub"],
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # Update existing user's Google info if needed
            if not user.google_id:
                user.google_id = idinfo["sub"]
                user.email = idinfo["email"]
                user.phone_number = idinfo.get("phoneNumber", "")
                db.commit()
                db.refresh(user)

        tokens = create_tokens(user.user_id)
        return {
            "user": UserPublic.model_validate(user),
            **tokens
        }

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token"
        )

@router.post("/refresh")
async def refresh_token(refresh_token: str, db: Session = Depends(get_session)):
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload["type"] != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        user_id = int(payload["sub"])
        user = db.get(User, user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Generate new tokens
        return create_tokens(user.user_id)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired"
        )
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
