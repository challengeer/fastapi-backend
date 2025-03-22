from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import uuid
from PIL import Image
from io import BytesIO
from enum import Enum

from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.challenge import Challenge, ChallengeStatus
from ..models.challenge_invitation import ChallengeInvitation, InvitationStatus
from ..models.challenge_submission import ChallengeSubmission
from ..models.submission_view import SubmissionView
from ..services.auth import get_current_user_id
from ..services.s3 import s3_client
from ..config import S3_BUCKET_NAME
from ..services.notifications import NotificationService

router = APIRouter(
    prefix="/challenges",
    tags=["Challenges"]
)

# Initialize notification service
notification_service = NotificationService()

class ChallengeCreate(BaseModel):
    title: str
    description: Optional[str] = None
    emoji: Optional[str] = "🎯"
    category: str

class ChallengeInviteCreate(BaseModel):
    challenge_id: int
    receiver_ids: List[int]

class ChallengeInviteAction(BaseModel):
    invitation_id: int

class UserChallengeStatus(str, Enum):
    PARTICIPANT = "participant"
    INVITED = "invited"
    SUBMITTED = "submitted"

class ParticipantInfo(UserPublic):
    has_submitted: bool

class ChallengeResponse(BaseModel):
    challenge_id: int
    creator_id: int
    title: str
    description: str
    emoji: str
    category: str
    start_date: datetime
    end_date: Optional[datetime]
    status: ChallengeStatus
    created_at: datetime
    creator: UserPublic
    participants: List[ParticipantInfo]
    has_new_submissions: bool
    user_status: UserChallengeStatus
    invitation_id: Optional[int] = None

class SubmissionResponse(BaseModel):
    submission_id: int
    challenge_id: int
    user_id: int
    photo_url: str
    caption: Optional[str]
    submitted_at: datetime
    user: UserPublic
    is_new: bool = False

class ChallengeInviteResponse(BaseModel):
    invitation_id: int
    challenge: Challenge
    creator: UserPublic
    sent_at: datetime

class ChallengePublic(BaseModel):
    challenge_id: int
    title: str
    emoji: str
    category: str
    end_date: Optional[datetime]

class SimpleChallengeResponse(ChallengePublic):
    has_new_submissions: bool

class SimpleInviteResponse(ChallengePublic):
    invitation_id: int
    sender: UserPublic

class ChallengesListResponse(BaseModel):
    challenges: List[SimpleChallengeResponse]
    invitations: List[SimpleInviteResponse]

@router.post("/create", response_model=Challenge)
def create_challenge(
    challenge: ChallengeCreate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    start_date = datetime.now()
    end_date = start_date + timedelta(days=2)

    new_challenge = Challenge(
        creator_id=current_user_id,
        title=challenge.title,
        description=challenge.description,
        emoji=challenge.emoji,
        category=challenge.category,
        start_date=start_date,
        end_date=end_date
    )
    session.add(new_challenge)
    session.commit()
    session.refresh(new_challenge)
    return new_challenge

@router.post("/invite")
async def invite_to_challenge(
    invite: ChallengeInviteCreate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Verify challenge exists and user is the creator
    challenge = session.exec(
        select(Challenge).where(Challenge.challenge_id == invite.challenge_id)
    ).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if challenge.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="Only challenge creator can send invites")
    if challenge.status != ChallengeStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Can only invite to active challenges")

    # Get sender's name
    sender = session.get(User, current_user_id)
    
    # Create invitations and send notifications
    invitations = []
    for receiver_id in invite.receiver_ids:
        # Get receiver with FCM token
        receiver = session.get(User, receiver_id)
        if not receiver:
            continue
            
        # Skip if invitation already exists
        existing = session.exec(
            select(ChallengeInvitation)
            .where(
                ChallengeInvitation.challenge_id == invite.challenge_id,
                ChallengeInvitation.receiver_id == receiver_id
            )
        ).first()
        if existing:
            continue

        invitation = ChallengeInvitation(
            challenge_id=invite.challenge_id,
            sender_id=current_user_id,
            receiver_id=receiver_id
        )
        session.add(invitation)
        session.flush()  # Get invitation ID
        invitations.append(invitation)

        # Send notification if receiver has FCM token
        if receiver.fcm_token:
            await notification_service.send_challenge_invite(
                fcm_token=receiver.fcm_token,
                sender_name=sender.display_name,
                challenge_title=challenge.title,
                challenge_id=challenge.challenge_id,
                invitation_id=invitation.invitation_id
            )

    session.commit()
    return {"message": f"Sent {len(invitations)} invitations"}

@router.put("/accept")
def accept_challenge(
    action: ChallengeInviteAction,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    invitation = session.get(ChallengeInvitation, action.invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.receiver_id != current_user_id:
        raise HTTPException(status_code=403, detail="Can only accept your own invitations")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Invitation is not pending")

    # Check if challenge is still active
    challenge = session.get(Challenge, invitation.challenge_id)
    if not challenge or challenge.status != ChallengeStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Challenge is not active")
    
    invitation.status = InvitationStatus.ACCEPTED
    invitation.responded_at = datetime.now()
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation

@router.put("/decline")
def decline_challenge(
    action: ChallengeInviteAction,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    invitation = session.get(ChallengeInvitation, action.invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.receiver_id != current_user_id:
        raise HTTPException(status_code=403, detail="Can only decline your own invitations")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Invitation is not pending")
    
    invitation.status = InvitationStatus.DECLINED
    invitation.responded_at = datetime.now()
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation

@router.get("/list", response_model=ChallengesListResponse)
def get_my_challenges(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get challenges where user is either creator or accepted participant
    statement = (
        select(Challenge)
        .where(
            (
                (Challenge.creator_id == current_user_id) |
                Challenge.challenge_id.in_(
                    select(ChallengeInvitation.challenge_id)
                    .where(
                        (ChallengeInvitation.receiver_id == current_user_id) &
                        (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
                    )
                )
            ) & (Challenge.end_date > datetime.now())
        )
    )
    results = session.exec(statement).all()
    
    challenges = []
    for challenge in results:
        # Check for new submissions
        new_submissions_exist = session.exec(
            select(ChallengeSubmission)
            .where(
                (ChallengeSubmission.challenge_id == challenge.challenge_id) &
                (ChallengeSubmission.user_id != current_user_id) &
                ~ChallengeSubmission.submission_id.in_(
                    select(SubmissionView.submission_id)
                    .where(SubmissionView.viewer_id == current_user_id)
                )
            )
        ).first() is not None
        
        challenges.append({
            "challenge_id": challenge.challenge_id,
            "title": challenge.title,
            "emoji": challenge.emoji,
            "category": challenge.category,
            "end_date": challenge.end_date,
            "has_new_submissions": new_submissions_exist
        })

    # Get pending invitations
    invites_statement = (
        select(ChallengeInvitation, Challenge, User)
        .join(Challenge, Challenge.challenge_id == ChallengeInvitation.challenge_id)
        .join(User, User.user_id == ChallengeInvitation.sender_id)
        .where(
            (ChallengeInvitation.receiver_id == current_user_id) &
            (ChallengeInvitation.status == InvitationStatus.PENDING) &
            (Challenge.end_date > datetime.now())
        )
    )
    invite_results = session.exec(invites_statement).all()
    
    invitations = []
    for invitation, challenge, sender in invite_results:
        invitations.append({
            "invitation_id": invitation.invitation_id,
            "challenge_id": challenge.challenge_id,
            "title": challenge.title,
            "emoji": challenge.emoji,
            "category": challenge.category,
            "end_date": challenge.end_date,
            "sender": sender
        })
    
    return {
        "challenges": challenges,
        "invitations": invitations
    }

@router.post("/{challenge_id}/submit", response_model=ChallengeSubmission)
async def submit_challenge_photo(
    challenge_id: int,
    caption: Optional[str] = None,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Check if challenge exists and is active
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if challenge.status != ChallengeStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Challenge is not active")

    # Check if user is participant or creator
    if challenge.creator_id != current_user_id:
        invitation = session.exec(
            select(ChallengeInvitation)
            .where(
                (ChallengeInvitation.challenge_id == challenge_id) &
                (ChallengeInvitation.receiver_id == current_user_id) &
                (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
            )
        ).first()
        if not invitation:
            raise HTTPException(status_code=403, detail="You are not a participant in this challenge")

    # Check if user already submitted
    existing_submission = session.exec(
        select(ChallengeSubmission)
        .where(
            (ChallengeSubmission.challenge_id == challenge_id) &
            (ChallengeSubmission.user_id == current_user_id)
        )
    ).first()
    if existing_submission:
        raise HTTPException(status_code=400, detail="You have already submitted to this challenge")

    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    try:
        # Read and process image
        contents = await file.read()
        image = Image.open(BytesIO(contents))
        
        # Convert to RGB if image is in RGBA mode
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        
        # Calculate new dimensions while maintaining aspect ratio
        max_size = 1200
        ratio = min(max_size/image.width, max_size/image.height)
        if ratio < 1:  # Only resize if image is larger than max_size
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save processed image to memory
        output = BytesIO()
        image.save(output, format='JPEG', quality=85)
        output.seek(0)
        
        # Generate unique filename
        filename = f"challenge-submissions/{challenge_id}/{current_user_id}-{uuid.uuid4()}.jpg"
        
        # Upload to S3
        s3_client.upload_fileobj(
            output,
            S3_BUCKET_NAME,
            filename,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        photo_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{filename}"
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to process or upload image")

    # Create submission
    submission = ChallengeSubmission(
        challenge_id=challenge_id,
        user_id=current_user_id,
        photo_url=photo_url,
        caption=caption
    )
    session.add(submission)
    session.commit()
    session.refresh(submission)

    # Get submitter and challenge info
    submitter = session.get(User, current_user_id)
    
    # Get all participants with their FCM tokens
    participants = session.exec(
        select(User)
        .join(ChallengeInvitation, User.user_id == ChallengeInvitation.receiver_id)
        .where(
            (ChallengeInvitation.challenge_id == challenge_id) &
            (ChallengeInvitation.status == InvitationStatus.ACCEPTED) &
            (User.user_id != current_user_id)  # Don't notify submitter
        )
    ).all()

    # Send notifications to all participants
    for participant in participants:
        if participant.fcm_token:
            await notification_service.send_challenge_submission(
                fcm_token=participant.fcm_token,
                submitter_name=submitter.display_name,
                challenge_title=challenge.title,
                challenge_id=challenge_id
            )

    return submission

@router.get("/{challenge_id}/submissions", response_model=List[SubmissionResponse])
async def get_challenge_submissions(
    challenge_id: int,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Check if challenge exists
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Check if user is participant or creator
    is_participant = False
    if challenge.creator_id == current_user_id:
        is_participant = True
    else:
        invitation = session.exec(
            select(ChallengeInvitation)
            .where(
                (ChallengeInvitation.challenge_id == challenge_id) &
                (ChallengeInvitation.receiver_id == current_user_id) &
                (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
            )
        ).first()
        if invitation:
            is_participant = True

    if not is_participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this challenge")

    # Check if user has submitted
    has_submitted = session.exec(
        select(ChallengeSubmission)
        .where(
            (ChallengeSubmission.challenge_id == challenge_id) &
            (ChallengeSubmission.user_id == current_user_id)
        )
    ).first() is not None

    if not has_submitted:
        raise HTTPException(
            status_code=403, 
            detail="You must submit your photo before viewing other submissions"
        )

    # Get all submissions with user information and view status
    statement = (
        select(ChallengeSubmission, User, SubmissionView)
        .join(User, User.user_id == ChallengeSubmission.user_id)
        .outerjoin(
            SubmissionView,
            (SubmissionView.submission_id == ChallengeSubmission.submission_id) &
            (SubmissionView.viewer_id == current_user_id)
        )
        .where(ChallengeSubmission.challenge_id == challenge_id)
    )
    results = session.exec(statement).all()

    # Create view records for newly seen submissions
    new_views = []
    submissions = []
    for submission, user, view in results:
        submission_dict = submission.model_dump()
        submission_dict["user"] = user
        submission_dict["is_new"] = view is None and submission.user_id != current_user_id

        # If this is a new submission (not viewed before and not own submission)
        if submission_dict["is_new"]:
            new_view = SubmissionView(
                submission_id=submission.submission_id,
                viewer_id=current_user_id
            )
            new_views.append(new_view)

        submissions.append(submission_dict)

    # Save view records
    if new_views:
        session.add_all(new_views)
        session.commit()

    return submissions

@router.get("/{challenge_id}/has-new", response_model=bool)
async def check_new_submissions(
    challenge_id: int,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    """Check if there are any new submissions in the challenge that the user hasn't seen."""
    
    # First verify user is participant
    if not session.exec(
        select(Challenge)
        .where(
            (Challenge.challenge_id == challenge_id) &
            (
                (Challenge.creator_id == current_user_id) |
                Challenge.challenge_id.in_(
                    select(ChallengeInvitation.challenge_id)
                    .where(
                        (ChallengeInvitation.receiver_id == current_user_id) &
                        (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
                    )
                )
            )
        )
    ).first():
        raise HTTPException(status_code=403, detail="You are not a participant in this challenge")

    # Check for new submissions
    new_submissions = session.exec(
        select(ChallengeSubmission)
        .where(
            (ChallengeSubmission.challenge_id == challenge_id) &
            (ChallengeSubmission.user_id != current_user_id) &
            ~ChallengeSubmission.submission_id.in_(
                select(SubmissionView.submission_id)
                .where(SubmissionView.viewer_id == current_user_id)
            )
        )
    ).first()

    return new_submissions is not None

@router.get("/{challenge_id}", response_model=ChallengeResponse)
def get_challenge_details(
    challenge_id: int,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Combine challenge, creator, user's invitation, and user's submission into one query
    statement = (
        select(Challenge, User, ChallengeInvitation, ChallengeSubmission)
        .join(User, User.user_id == Challenge.creator_id)
        .outerjoin(
            ChallengeInvitation,
            (ChallengeInvitation.challenge_id == Challenge.challenge_id) &
            (ChallengeInvitation.receiver_id == current_user_id)
        )
        .outerjoin(
            ChallengeSubmission,
            (ChallengeSubmission.challenge_id == Challenge.challenge_id) &
            (ChallengeSubmission.user_id == current_user_id)
        )
        .where(Challenge.challenge_id == challenge_id)
    )
    result = session.exec(statement).first()
    if not result:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    challenge, creator, user_invitation, user_submission = result

    # Check participation status and authorization in one go
    is_creator = challenge.creator_id == current_user_id
    if not (is_creator or (user_invitation and user_invitation.status in [InvitationStatus.ACCEPTED, InvitationStatus.PENDING])):
        raise HTTPException(status_code=403, detail="You are not a participant in this challenge")

    # Get all participants and their submissions in a single query
    participants_query = (
        select(User, ChallengeSubmission)
        .join(
            ChallengeInvitation,
            (ChallengeInvitation.receiver_id == User.user_id) &
            (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
        )
        .outerjoin(
            ChallengeSubmission,
            (ChallengeSubmission.user_id == User.user_id) &
            (ChallengeSubmission.challenge_id == challenge_id)
        )
        .where(ChallengeInvitation.challenge_id == challenge_id)
    )
    participant_results = session.exec(participants_query).all()

    # Determine user status and invitation_id
    if user_submission:
        user_status = UserChallengeStatus.SUBMITTED
        invitation_id = None
    elif is_creator:
        user_status = UserChallengeStatus.PARTICIPANT
        invitation_id = None
    elif user_invitation:
        if user_invitation.status == InvitationStatus.ACCEPTED:
            user_status = UserChallengeStatus.PARTICIPANT
            invitation_id = None
        else:  # PENDING
            user_status = UserChallengeStatus.INVITED
            invitation_id = user_invitation.invitation_id

    # Check for new submissions with a more efficient query
    new_submissions_exist = session.exec(
        select(ChallengeSubmission.submission_id)
        .where(
            (ChallengeSubmission.challenge_id == challenge_id) &
            (ChallengeSubmission.user_id != current_user_id) &
            ~ChallengeSubmission.submission_id.in_(
                select(SubmissionView.submission_id)
                .where(SubmissionView.viewer_id == current_user_id)
            )
        )
        .limit(1)  # Only need to know if any exist
    ).first() is not None

    return {
        **challenge.model_dump(),
        "creator": creator,
        "participants": [
            {
                **user.model_dump(),
                "has_submitted": submission is not None
            }
            for user, submission in participant_results
        ],
        "has_new_submissions": new_submissions_exist,
        "user_status": user_status,
        "invitation_id": invitation_id
    }