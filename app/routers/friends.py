from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, and_
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List

from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.friend_request import FriendRequest, RequestStatus
from ..models.friendship import Friendship
from ..services.auth import get_current_user_id
from ..models.challenge_submission import ChallengeSubmission
from ..services.notification import NotificationService

router = APIRouter(
    prefix="/friends",
    tags=["Friends"]
)

# Initialize notification service
notification_service = NotificationService()

class FriendRequestCreate(BaseModel):
    receiver_id: int

class FriendRequestAction(BaseModel):
    request_id: int

class FriendWithStreak(UserPublic):
    mutual_streak: int = 0
    total_mutual_challenges: int = 0

def calculate_mutual_streak(user1_id: int, user2_id: int, session: Session) -> tuple[int, int]:
    # Get dates where both users completed the same challenges
    mutual_submissions = session.exec(
        select(ChallengeSubmission.challenge_id, ChallengeSubmission.submitted_at)
        .where(ChallengeSubmission.user_id == user1_id)
        .where(
            ChallengeSubmission.challenge_id.in_(
                select(ChallengeSubmission.challenge_id)
                .where(ChallengeSubmission.user_id == user2_id)
            )
        )
    ).all()
    
    user2_submissions = {
        sub.challenge_id: sub.submitted_at.date()
        for sub in session.exec(
            select(ChallengeSubmission)
            .where(
                and_(
                    ChallengeSubmission.user_id == user2_id,
                    ChallengeSubmission.challenge_id.in_([s.challenge_id for s in mutual_submissions])
                )
            )
        ).all()
    }
    
    # Find dates where both users completed the same challenges
    mutual_dates = set()
    for challenge_id, submitted_at in mutual_submissions:
        user1_date = submitted_at.date()
        user2_date = user2_submissions[challenge_id]
        # Only count if both users completed the challenge on the same day or within 1 day
        if abs((user1_date - user2_date).days) <= 1:
            mutual_dates.add(user1_date)
    
    if not mutual_dates:
        return 0, 0
        
    # Convert to sorted list for streak calculation
    mutual_dates = sorted(mutual_dates, reverse=True)
    
    # Get total mutual challenges
    total_mutual = len(mutual_dates)
    
    # Check if there's mutual activity in the last 3 days
    today = datetime.now().date()
    if (today - mutual_dates[0]) > timedelta(days=3):
        return 0, total_mutual
        
    streak = 1
    allowed_gap = timedelta(days=3)
    
    # Calculate streak from mutual completion dates
    for i in range(1, len(mutual_dates)):
        gap = mutual_dates[i-1] - mutual_dates[i]
        if gap <= allowed_gap:
            streak += 1
        else:
            break
            
    return streak, total_mutual


@router.post("/add", response_model=FriendRequest)
async def send_friend_request(
    request: FriendRequestCreate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Check if not self
    if current_user_id == request.receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
    
    # Check if user exists
    receiver = session.get(User, request.receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    # Check if any friend request exists in either direction
    statement = select(FriendRequest).where(
        ((FriendRequest.sender_id == current_user_id) & (FriendRequest.receiver_id == request.receiver_id)) |
        ((FriendRequest.sender_id == request.receiver_id) & (FriendRequest.receiver_id == current_user_id))
    )
    existing_request = session.exec(statement).first()
    
    if existing_request:
        # If there's a pending request from the other user, accept it automatically
        if (existing_request.status == RequestStatus.PENDING and 
            existing_request.receiver_id == current_user_id):
            existing_request.status = RequestStatus.ACCEPTED
            
            # Create friendship record
            new_friendship = Friendship(
                user1_id=existing_request.sender_id,
                user2_id=existing_request.receiver_id
            )
            session.add(new_friendship)
            session.add(existing_request)
            session.commit()
            session.refresh(existing_request)
            return existing_request
            
        elif existing_request.status != RequestStatus.REJECTED:
            raise HTTPException(status_code=400, detail="Active friend request already exists")
            
        # If the request was rejected and the original sender is trying again, prevent it
        if existing_request.sender_id == current_user_id:
            raise HTTPException(status_code=400, detail="Cannot send another request after being rejected")
            
        # Only allow the person who rejected to send a new request
        existing_request.status = RequestStatus.PENDING
        existing_request.sender_id = request.receiver_id
        existing_request.receiver_id = current_user_id
        session.add(existing_request)
        session.commit()
        session.refresh(existing_request)
        return existing_request

    # Create new friend request if none exists
    new_request = FriendRequest(
        sender_id=current_user_id,
        receiver_id=request.receiver_id
    )
    session.add(new_request)
    
    # Get sender and receiver info
    sender = session.get(User, current_user_id)
    receiver = session.get(User, request.receiver_id)
    
    # Send notification to receiver if they have FCM token
    if receiver.fcm_token:
        await notification_service.send_friend_request(
            db=session,
            user_id=receiver.user_id,
            sender_name=sender.display_name,
            sender_id=sender.user_id
        )
    
    session.commit()
    session.refresh(new_request)
    return new_request

@router.put("/accept", response_model=Friendship)
async def accept_friend_request(
    request: FriendRequestAction,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    friend_request = session.get(FriendRequest, request.request_id)
    if not friend_request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if friend_request.receiver_id != current_user_id:
        raise HTTPException(status_code=403, detail="Can only accept your own friend requests")
    
    if friend_request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Friend request is not pending")
    
    friend_request.status = RequestStatus.ACCEPTED
    
    # Create friendship record
    new_friendship = Friendship(
        user1_id=min(current_user_id, friend_request.sender_id),
        user2_id=max(current_user_id, friend_request.sender_id)
    )
    session.add(new_friendship)
    
    # Get user info
    accepter = session.get(User, current_user_id)
    sender = session.get(User, friend_request.sender_id)
    
    # Send notification to request sender
    if sender.fcm_token:
        await notification_service.send_friend_accept(
            db=session,
            user_id=sender.user_id,
            accepter_name=accepter.display_name,
            accepter_id=accepter.user_id
        )
    
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return new_friendship

@router.put("/reject")
def reject_friend_request(
    request: FriendRequestAction,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    friend_request = session.get(FriendRequest, request.request_id)
    if not friend_request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if friend_request.receiver_id != user_id:
        raise HTTPException(status_code=403, detail="Can only reject your own friend requests")
    
    if friend_request.status != RequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Friend request is not pending")
    
    friend_request.status = RequestStatus.REJECTED
    session.add(friend_request)
    session.commit()
    session.refresh(friend_request)
    return friend_request

@router.get("/list", response_model=list[FriendWithStreak])
def get_friends(
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    # First get all friends
    statement = (
        select(User)
        .join(
            Friendship,
            (Friendship.user2_id == User.user_id) & (Friendship.user1_id == user_id) |
            (Friendship.user1_id == User.user_id) & (Friendship.user2_id == user_id)
        )
    )
    
    friends = session.exec(statement).all()
    friends_with_streaks = []
    
    for friend in friends:
        # Calculate mutual streak and total mutual challenges
        mutual_streak, total_mutual = calculate_mutual_streak(user_id, friend.user_id, session)
        
        # Create friend response with streak info
        friend_dict = friend.model_dump()
        friend_dict["mutual_streak"] = mutual_streak
        friend_dict["total_mutual_challenges"] = total_mutual
        friends_with_streaks.append(friend_dict)
    
    return friends_with_streaks

class FriendRequestPublic(UserPublic):
    request_id: int
    status: RequestStatus

@router.get("/requests", response_model=list[FriendRequestPublic])
def get_friend_requests(session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    statement = (
        select(User, FriendRequest)
            .join(FriendRequest, FriendRequest.sender_id == User.user_id)
            .where((FriendRequest.receiver_id == user_id) & (FriendRequest.status == RequestStatus.PENDING))
    )
    results = session.exec(statement).all()

    friend_requests = []
    for user, request in results:
        friend_requests.append(FriendRequestPublic(
            request_id=request.request_id,
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            profile_picture=user.profile_picture,
            status=request.status
        ))

    return friend_requests