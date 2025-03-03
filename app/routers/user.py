from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
from enum import Enum
import uuid
from PIL import Image
from io import BytesIO
import re

from ..database import get_session
from ..models.user import User, UserPublic
from ..models.friendship import Friendship
from ..models.friend_request import FriendRequest, RequestStatus
from ..auth import get_current_user_id, validate_username
from ..s3 import s3_client
from ..config import S3_BUCKET_NAME

router = APIRouter(
    prefix="/user",
    tags=["User"]
)

class FriendshipStatus(str, Enum):
    FRIENDS = "friends"
    REQUEST_SENT = "request_sent"
    REQUEST_RECEIVED = "request_received"
    NONE = "none"

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

class UserLocal(UserPublic):
    email: Optional[str]
    phone_number: Optional[str]

@router.get("/me", response_model=UserLocal)
def read_current_user(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    user = session.exec(select(User).where(User.user_id == current_user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

class UserProfile(UserPublic):
    request_id: Optional[int]
    friendship_status: FriendshipStatus
    
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
def update_username(
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
def update_display_name(
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
    # Get current user and their existing profile picture
    user = session.exec(
        select(User.profile_picture).where(User.user_id == current_user_id)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Extract old image key if it exists
    old_image_key = None
    if user.profile_picture:
        match = re.search(r'profile-pictures/.*$', user.profile_picture)
        if match:
            old_image_key = match.group(0)

    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    # Read and process image
    try:
        # Read image into memory
        contents = await file.read()
        image = Image.open(BytesIO(contents))
        
        # Convert to RGB if image is in RGBA mode
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        
        # Calculate new dimensions while maintaining aspect ratio
        max_size = 400
        ratio = min(max_size/image.width, max_size/image.height)
        if ratio < 1:  # Only resize if image is larger than max_size
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save processed image to memory
        output = BytesIO()
        image.save(output, format='JPEG', quality=85)
        output.seek(0)
        
        # Generate unique filename
        new_filename = f"profile-pictures/{current_user_id}-{uuid.uuid4()}.jpg"
        
        # Upload to S3
        s3_client.upload_fileobj(
            output,
            S3_BUCKET_NAME,
            new_filename,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{new_filename}"

        # Delete old image if it exists
        if old_image_key:
            try:
                s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=old_image_key)
            except Exception:
                # Log error but don't fail the request if deletion fails
                print(f"Failed to delete old profile picture: {old_image_key}")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to process or upload image")
    
    # Update user profile picture URL
    user.profile_picture = s3_url
    session.add(user)
    session.commit()
    session.refresh(user)
    return user