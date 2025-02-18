from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timezone, timedelta
import secrets

from ..database import get_session
from ..models.verification_code import VerificationCode, VerificationCodeCreate, VerificationCodeVerify
from ..models.user import User

router = APIRouter(
    prefix="/verification-code",
    tags=["Verification Code"]
)

@router.post("/")
def create_verification_code(*, session: Session = Depends(get_session), request: VerificationCodeCreate):
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

@router.post("/verify")
def verify_code(*, session: Session = Depends(get_session), request: VerificationCodeVerify):
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