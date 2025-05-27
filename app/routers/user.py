from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta
from enum import Enum

from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.friendship import Friendship
from ..models.friend_request import FriendRequest, RequestStatus
from ..services.auth import get_current_user_id, validate_username
from ..services.s3 import upload_image, extract_key_from_url, delete_file
from ..models.submission import Submission
from ..models.submission_overlay import SubmissionOverlay
from ..models.submission_view import SubmissionView
from ..models.contact import Contact
from ..models.device import Device
from ..services.notification import NotificationService

router = APIRouter(
    prefix="/user",
    tags=["User"]
)

# Initialize notification service
notification_service = NotificationService()

# Constants for streak calculation
MAX_STREAK_GAP_DAYS = 3  # Maximum allowed gap between active days to maintain streak

class FriendshipStatus(str, Enum):
    FRIENDS = "friends"
    REQUEST_SENT = "request_sent"
    REQUEST_RECEIVED = "request_received"
    NONE = "none"

def calculate_streak(completion_dates: List[datetime]) -> int:
    if not completion_dates:
        return 0
        
    # Convert to dates only (ignore time) and get unique dates
    unique_dates = sorted(set(d.date() for d in completion_dates), reverse=True)
    
    # Check if there's activity today or in the last 3 days
    today = datetime.now().date()
    if (today - unique_dates[0]) > timedelta(days=MAX_STREAK_GAP_DAYS):
        return 0  # Streak is broken if no activity in last 3 days
        
    streak = 1
    allowed_gap = timedelta(days=MAX_STREAK_GAP_DAYS)  # Maximum allowed gap between active days
    
    # Start from the second most recent date
    for i in range(1, len(unique_dates)):
        gap = unique_dates[i-1] - unique_dates[i]
        if gap <= allowed_gap:
            streak += 1
        else:
            break
            
    return streak


class UserMe(UserPublic):
    email: Optional[str]
    phone_number: Optional[str]

@router.get("/me", response_model=UserMe)
def read_current_user(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    user = session.exec(
        select(User).where(User.user_id == current_user_id)
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


class SearchUser(UserPublic):
    request_id: Optional[int]
    friendship_status: FriendshipStatus

@router.get("/search", response_model=List[UserPublic])
def search_users(
    q: str = "",
    skip: int = 0,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # If query is empty, return empty results
    if not q:
        return []

    statement = (
        select(User)
        .where(
            (User.display_name.ilike(f"%{q}%")) | (User.username.ilike(f"%{q}%"))
        )
        .offset(skip)
        .limit(limit)
    )
    
    results = session.exec(statement).all()
    users = []
    
    for user in results:
        if user.user_id == current_user_id:
            continue  # Skip the current user
        users.append(user)
    
    return users


class UserProfile(UserPublic):
    request_id: Optional[int]
    friendship_status: FriendshipStatus
    challenge_completion_dates: List[datetime] = []
    total_challenges_completed: int = 0
    current_streak: int = 0

@router.get("/{user_id}", response_model=UserProfile)
def read_user(
    user_id: int, 
    session: Session = Depends(get_session), 
    current_user_id: int = Depends(get_current_user_id)
):
    statement = (
        select(User, Friendship, FriendRequest)
        .outerjoin(
            Friendship,
            ((Friendship.user1_id == User.user_id) & (Friendship.user2_id == current_user_id)) |
            ((Friendship.user2_id == User.user_id) & (Friendship.user1_id == current_user_id))
        )
        .outerjoin(
            FriendRequest,
            (FriendRequest.receiver_id == User.user_id) & (FriendRequest.sender_id == current_user_id) |
            (FriendRequest.receiver_id == current_user_id) & (FriendRequest.sender_id == user_id)
        )
        .where(User.user_id == user_id)
    )
    
    result = session.exec(statement).first()
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
        
    user, friendship, request = result
    user_dict = user.model_dump()
    
    # Get challenge completion dates and count
    completion_dates = session.exec(
        select(Submission.submitted_at)
        .where(Submission.user_id == user_id)
        .order_by(Submission.submitted_at.desc())
    ).all()
    
    user_dict["challenge_completion_dates"] = completion_dates
    user_dict["total_challenges_completed"] = len(completion_dates)
    user_dict["current_streak"] = calculate_streak(completion_dates)
    
    if friendship:
        user_dict["request_id"] = None
        user_dict["friendship_status"] = FriendshipStatus.FRIENDS
    elif request:
        user_dict["request_id"] = request.request_id
        if request.status == RequestStatus.PENDING:
            user_dict["friendship_status"] = (
                FriendshipStatus.REQUEST_SENT if request.sender_id == current_user_id 
                else FriendshipStatus.REQUEST_RECEIVED
            )
        elif request.status == RequestStatus.REJECTED:
            user_dict["friendship_status"] = FriendshipStatus.NONE
    else:
        user_dict["request_id"] = None
        user_dict["friendship_status"] = FriendshipStatus.NONE
    
    return user_dict


class UpdateUsernameRequest(BaseModel):
    username: str

class UpdateDisplayNameRequest(BaseModel):
    display_name: str

@router.put("/username", response_model=UserPublic)
async def update_username(
    request: UpdateUsernameRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    validated_username = validate_username(request.username)

    # Check if username is taken
    existing_user = session.exec(
        select(User).where(User.username == validated_username)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Update username
    user = session.exec(select(User).where(User.user_id == current_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.username = validated_username
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.put("/display-name", response_model=UserPublic)
async def update_display_name(
    request: UpdateDisplayNameRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    user = session.get(User, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.display_name = request.display_name
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.put("/profile-picture", response_model=UserPublic)
async def update_profile_picture(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Get current user and their existing profile picture
    user = session.get(User, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete old profile picture if it exists
    if user.profile_picture:
        old_key = extract_key_from_url(user.profile_picture)
        if old_key:
            delete_file(old_key)

    # Read the file contents before passing to upload_image
    file_content = await file.read()
    
    s3_url = await upload_image(
        file_content=file_content,
        folder="profile-pictures",
        identifier=str(current_user_id),
        width=400,
        height=400
    )

    # Update user profile picture URL
    user.profile_picture = s3_url
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@router.delete("/me", status_code=204)
async def delete_user(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get user and verify existence
    user = session.get(User, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete profile picture from S3 if exists
    if user.profile_picture:
        old_key = extract_key_from_url(user.profile_picture)
        if old_key:
            delete_file(old_key)

    # Get all submission photo URLs before deleting the records
    submissions = session.exec(
        select(Submission)
        .where(Submission.user_id == current_user_id)
    ).all()
    
    photo_urls = [submission.photo_url for submission in submissions]

    # Delete in correct order to handle foreign key constraints
    
    # 1. Delete submission views first
    session.exec(
        select(SubmissionView).where(
            SubmissionView.submission_id.in_(
                select(Submission.submission_id)
                .where(Submission.user_id == current_user_id)
            )
        )
    ).delete()

    # 2. Delete submission overlays
    session.exec(
        select(SubmissionOverlay).where(
            SubmissionOverlay.submission_id.in_(
                select(Submission.submission_id)
                .where(Submission.user_id == current_user_id)
            )
        )
    ).delete()

    # 3. Delete submissions
    session.exec(
        select(Submission).where(Submission.user_id == current_user_id)
    ).delete()

    # 4. Delete contacts
    session.exec(
        select(Contact).where(Contact.user_id == current_user_id)
    ).delete()

    # 5. Delete devices
    session.exec(
        select(Device).where(Device.user_id == current_user_id)
    ).delete()

    # 6. Delete all friendships
    session.exec(
        select(Friendship).where(
            (Friendship.user1_id == current_user_id) | 
            (Friendship.user2_id == current_user_id)
        )
    ).delete()

    # 7. Delete all friend requests (both sent and received)
    session.exec(
        select(FriendRequest).where(
            (FriendRequest.sender_id == current_user_id) | 
            (FriendRequest.receiver_id == current_user_id)
        )
    ).delete()

    # 8. Delete the user
    session.delete(user)
    session.commit()

    # After successful database deletion, delete the S3 photos
    for photo_url in photo_urls:
        try:
            delete_file(extract_key_from_url(photo_url))
        except Exception as e:
            print(f"Failed to delete S3 photo {photo_url}: {e}")
            # Continue with other deletions even if one fails