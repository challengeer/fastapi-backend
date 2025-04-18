from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel
from datetime import timedelta
import firebase_admin
from firebase_admin import auth, credentials
import secrets

from ..services.auth import create_token, verify_token, normalize_username, validate_username, get_current_user_id
from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.device import Device, DeviceCreate
from ..config import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, FIREBASE_CREDENTIALS_JSON

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

# Initialize Firebase Admin
cred = credentials.Certificate(FIREBASE_CREDENTIALS_JSON)
firebase_admin.initialize_app(cred)

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


class GoogleAuthRequest(BaseModel):
    id_token: str
    fcm_token: str

class GoogleAuthResponse(BaseModel):
    user: UserPublic
    access_token: str
    refresh_token: str

@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth(request: GoogleAuthRequest, db: Session = Depends(get_session)):
    try:
        print(request.id_token)
        # Verify the Firebase token
        decoded_token = auth.verify_id_token(request.id_token)
        print(decoded_token)
        uid = decoded_token['uid']
        email = decoded_token.get('email')
        phone_number = decoded_token.get('phone_number')
        name = decoded_token.get('name', '')
        picture = decoded_token.get('picture')

        # Split name into first and last name
        name_parts = name.split(' ', 1)
        first_name = name_parts[0] if name_parts else 'user'
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        # Check if user exists by Firebase UID
        user = db.exec(
            select(User).where(User.firebase_uid == uid)
        ).first()

        # If user doesn't exist, create a new user
        if not user:
            username = generate_username(first_name, last_name)
            
            # Ensure username is unique
            while db.exec(select(User).where(User.username == username)).first():
                username = generate_username(first_name, last_name)
            
            # Create new user
            user = User(
                username=username,
                display_name=name or username,
                profile_picture=picture,
                email=email,
                phone_number=phone_number,
                firebase_uid=uid
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # Handle device registration
        if request.fcm_token:
            existing_device = db.exec(
                select(Device).where(
                    (Device.user_id == user.user_id) &
                    (Device.fcm_token == request.fcm_token)
                )
            ).first()

            if not existing_device:
                device = Device(
                    user_id=user.user_id,
                    fcm_token=request.fcm_token,
                    brand=request.brand,
                    model_name=request.model_name,
                    os_name=request.os_name,
                    os_version=request.os_version
                )
                db.add(device)
                db.commit()

        tokens = create_tokens(user.user_id)
        return {
            "user": UserPublic.model_validate(user),
            **tokens
        }

    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


class LogoutRequest(BaseModel):
    fcm_token: str | None = None

@router.post("/logout")
async def logout(
    request: LogoutRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_session)
):
    if request.fcm_token:
        # Remove the device with matching FCM token for this user
        device = db.exec(
            select(Device).where(
                (Device.user_id == current_user_id) &
                (Device.fcm_token == request.fcm_token)
            )
        ).first()
        
        if device:
            db.delete(device)
            db.commit()
    
    return {"message": "Logged out successfully"}


class RefreshTokenRequest(BaseModel):
    refresh_token: str

class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str

@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_session)):
    payload = verify_token(request.refresh_token)
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


class PhoneVerificationRequest(BaseModel):
    phone_number: str
    id_token: str  # Firebase ID token to verify the user is authenticated

class PhoneVerificationResponse(BaseModel):
    message: str
    phone_number: str

@router.post("/verify-phone", response_model=PhoneVerificationResponse)
async def create_phone_verification(
    request: PhoneVerificationRequest,
    db: Session = Depends(get_session)
):
    try:
        # Verify the Firebase token
        decoded_token = auth.verify_id_token(request.id_token)
        uid = decoded_token['uid']
        
        # Get the user
        user = db.exec(
            select(User).where(User.firebase_uid == uid)
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Check if phone number is already registered by another user
        existing_user = db.exec(
            select(User).where(
                (User.phone_number == request.phone_number) &
                (User.user_id != user.user_id)
            )
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered"
            )
        
        # Update user's phone number
        user.phone_number = request.phone_number
        db.add(user)
        db.commit()
        
        return {
            "message": "Phone number updated successfully",
            "phone_number": request.phone_number
        }
        
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


class UsernameCheckResponse(BaseModel):
    username: str
    exists: bool

@router.get("/check-username", response_model=UsernameCheckResponse)
def check_username_exists(username: str, session: Session = Depends(get_session)):
    validated_username = validate_username(username)
    statement = select(User).where(User.username == validated_username)
    existing_user = session.exec(statement).first()
    return UsernameCheckResponse(
        username=validated_username,
        exists=existing_user is not None
    )