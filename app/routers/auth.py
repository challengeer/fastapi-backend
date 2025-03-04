from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel
from datetime import datetime, timezone,timedelta
from jose import jwt
from google.oauth2 import id_token
from google.auth.transport import requests
import secrets

from ..auth import create_token, normalize_username, validate_username
from ..database import get_session
from ..models.user import User, UserPublic
from ..models.verification_code import VerificationCode, VerificationCodeCreate, VerificationCodeVerify
from ..config import GOOGLE_CLIENT_ID, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

class GoogleAuthRequest(BaseModel):
    token: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class UsernameCheckResponse(BaseModel):
    username: str
    exists: bool

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

def generate_username(first_name: str, last_name: str) -> str:
    first_name = normalize_username(first_name)
    last_name = normalize_username(last_name) if last_name else ""
    random_numbers = "".join([str(secrets.randbelow(10)) for _ in range(4)])
    
    if last_name:
        # username format: f_lastname1234
        # If last name is longer than 9 characters, truncate it because the username is max 15 characters long
        username = f"{first_name[0]}_{last_name[:9]}{random_numbers}"
    else:
        # username format: firstname1234
        username = f"{first_name[:11]}{random_numbers}"
    
    return username

@router.post("/google")
async def google_auth(request: GoogleAuthRequest, db: Session = Depends(get_session)):
    try:
        idinfo = id_token.verify_oauth2_token(
            request.token, requests.Request(), GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )

        user = db.exec(
            select(User).where(
                (User.google_id == idinfo["sub"]) &
                (User.email == idinfo["email"])
            )
        ).first()

        if not user:
            # Get first and last name from Google token
            first_name = idinfo.get("given_name", "user")
            last_name = idinfo.get("family_name", "")
            username = generate_username(first_name, last_name)
            
            # Ensure username is unique
            while db.exec(select(User).where(User.username == username)).first():
                username = generate_username(first_name, last_name)
            
            # Create new user
            user = User(
                username=username,
                display_name=idinfo.get("name", username),
                profile_picture=idinfo.get("picture"),
                email=idinfo["email"],
                google_id=idinfo["sub"],
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # Update existing user's Google info
            if not user.google_id:
                user.google_id = idinfo["sub"]
                user.email = idinfo["email"]
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
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_session)):
    try:
        payload = jwt.decode(request.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        user_id = int(payload.get("sub"))
        user = db.exec(
            select(User).where(User.user_id == user_id)
        ).first()
        
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

@router.post("/verify-phone")
def create_verification_code(request: VerificationCodeCreate, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.phone_number == request.phone_number)).first()
    if user:
        raise HTTPException(status_code=400, detail="Phone number already registered")
    
    verification_code = str(secrets.randbelow(900000) + 100000)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    # Check if the phone number already exists
    existing_record = session.get(VerificationCode, request.phone_number)
    if existing_record:
        # Update the record if it exists
        existing_record.verification_code = verification_code
        existing_record.expires_at = expires_at
        existing_record.created_at = datetime.now(timezone.utc)
        existing_record.verified = False
        session.add(existing_record)
    else:
        # Create a new record
        new_code = VerificationCode(
            phone_number=request.phone_number,
            verification_code=verification_code,
            expires_at=expires_at,
        )
        session.add(new_code)

    session.commit()
    return {"message": "Verification code created", "phone_number": request.phone_number}

@router.post("/verify-phone/confirm")
def verify_code(request: VerificationCodeVerify, session: Session = Depends(get_session)):
    verification_code = session.get(VerificationCode, request.phone_number)

    if not verification_code:
        raise HTTPException(status_code=404, detail="Phone number not found")

    if verification_code.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Verification code expired")

    if verification_code.verified:
        raise HTTPException(status_code=400, detail="Verification code already used")

    if verification_code.verification_code != request.verification_code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Mark as verified
    verification_code.verified = True
    session.add(verification_code)
    session.commit()

    return {"message": "Verification successful"}

@router.get("/check-username", response_model=UsernameCheckResponse)
def check_username_exists(username: str, session: Session = Depends(get_session)):
    validated_username = validate_username(username)
    statement = select(User).where(User.username == validated_username)
    existing_user = session.exec(statement).first()
    return UsernameCheckResponse(
        username=validated_username,
        exists=existing_user is not None
    )