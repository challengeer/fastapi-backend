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
from ..models.challenge_submission import ChallengeSubmission
from ..services.notification import NotificationService

router = APIRouter(
    prefix="/user",
    tags=["User"]
)

# Initialize notification service
notification_service = NotificationService()

class FriendshipStatus(str, Enum):
    FRIENDS = "friends"
    REQUEST_SENT = "request_sent"
    REQUEST_RECEIVED = "request_received"
    NONE = "none"

def calculate_streak(completion_dates: List[datetime]) -> int:
    if not completion_dates:
        return 0
        
    # Convert to dates only (ignore time) and sort in descending order
    dates = sorted([d.date() for d in completion_dates], reverse=True)
    
    # Check if there's activity today or in the last 3 days
    today = datetime.now().date()
    if (today - dates[0]) > timedelta(days=3):
        return 0  # Streak is broken if no activity in last 3 days
        
    streak = 1
    allowed_gap = timedelta(days=3)  # Maximum allowed gap between challenges
    
    # Start from the second most recent date
    for i in range(1, len(dates)):
        gap = dates[i-1] - dates[i]
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

class SearchUsersResponse(BaseModel):
    friends: list[SearchUser]
    request_sent: list[SearchUser]
    request_received: list[SearchUser]
    none: list[SearchUser]

@router.get("/search", response_model=SearchUsersResponse)
def search_users(
    q: str = "",
    skip: int = 0,
    limit: int = 20,
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
            (FriendRequest.receiver_id == current_user_id) & (FriendRequest.sender_id == User.user_id)
        )
        .where(
            (User.display_name.like(f"%{q}%")) | (User.username.like(f"%{q}%"))
        )
        .offset(skip)
        .limit(limit)
    )
    
    results = session.exec(statement).all()
    
    categorized_users = {
        "friends": [],
        "request_sent": [],
        "request_received": [],
        "none": []
    }
    
    for user, friendship, request in results:
        if user.user_id == current_user_id:
            continue  # Skip the current user
            
        user_dict = user.model_dump()
        if friendship:
            user_dict["request_id"] = None
            user_dict["friendship_status"] = FriendshipStatus.FRIENDS
            categorized_users["friends"].append(user_dict)
        elif request:
            user_dict["request_id"] = request.request_id
            if request.status == RequestStatus.PENDING:
                if request.sender_id == current_user_id:
                    user_dict["friendship_status"] = FriendshipStatus.REQUEST_SENT
                    categorized_users["request_sent"].append(user_dict)
                else:
                    user_dict["friendship_status"] = FriendshipStatus.REQUEST_RECEIVED
                    categorized_users["request_received"].append(user_dict)
            elif request.status == RequestStatus.REJECTED:
                user_dict["friendship_status"] = FriendshipStatus.NONE
                categorized_users["none"].append(user_dict)
        else:
            user_dict["request_id"] = None
            user_dict["friendship_status"] = FriendshipStatus.NONE
            categorized_users["none"].append(user_dict)
    
    return categorized_users


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
        select(ChallengeSubmission.submitted_at)
        .where(ChallengeSubmission.user_id == user_id)
        .order_by(ChallengeSubmission.submitted_at.desc())
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