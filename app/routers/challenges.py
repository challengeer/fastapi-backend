from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select, delete
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from enum import Enum

from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.challenge import Challenge, ChallengeStatus
from ..models.challenge_invitation import ChallengeInvitation, InvitationStatus
from ..models.challenge_submission import ChallengeSubmission
from ..models.submission_view import SubmissionView
from ..services.auth import get_current_user_id
from ..services.s3 import upload_image, delete_file, extract_key_from_url
from ..services.notification import NotificationService

router = APIRouter(
    prefix="/challenges",
    tags=["Challenges"]
)

# Initialize notification service
notification_service = NotificationService()

def has_new_submissions(session: Session, challenge_id: int, current_user_id: int) -> bool:
    return session.exec(
        select(1)
        .where(
            (ChallengeSubmission.challenge_id == challenge_id) &
            (ChallengeSubmission.user_id != current_user_id) &
            ~ChallengeSubmission.submission_id.in_(
                select(SubmissionView.submission_id)
                .where(SubmissionView.viewer_id == current_user_id)
            )
        )
        .limit(1)
    ).first() is not None

class UserChallengeStatus(str, Enum):
    PARTICIPANT = "participant"
    INVITED = "invited"
    SUBMITTED = "submitted"

class ParticipantInfo(UserPublic):
    has_submitted: bool

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
    duration: Optional[int]

class SimpleInviteResponse(ChallengePublic):
    invitation_id: int
    sender: UserPublic


class ChallengeCreate(BaseModel):
    title: str
    description: Optional[str] = None
    emoji: Optional[str] = "🎯"
    category: str
    lifetime: Optional[int] = 48  # How long the challenge is open (in hours)
    duration: Optional[int] = 30  # How long users should spend doing the activity (in minutes)

@router.post("/create", response_model=Challenge)
def create_challenge(
    challenge: ChallengeCreate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    if challenge.lifetime <= 0:
        raise HTTPException(
            status_code=400,
            detail="Lifetime must be greater than 0 hours"
        )
    if challenge.lifetime > 168:  # 168 hours in hours
        raise HTTPException(
            status_code=400,
            detail="Lifetime cannot exceed 168 hours"
        )
    
    start_date = datetime.now()
    end_date = start_date + timedelta(hours=challenge.lifetime)

    if challenge.duration <= 0:
        raise HTTPException(
            status_code=400,
            detail="Duration must be greater than 0 minutes"
        )
    if challenge.duration > 1440:  # 24 hours in minutes
        raise HTTPException(
            status_code=400,
            detail="Duration cannot exceed 24 hours (1440 minutes)"
        )

    new_challenge = Challenge(
        creator_id=current_user_id,
        title=challenge.title,
        description=challenge.description,
        emoji=challenge.emoji,
        category=challenge.category,
        start_date=start_date,
        end_date=end_date,
        duration=challenge.duration,
        lifetime=challenge.lifetime
    )
    session.add(new_challenge)
    session.flush()  # Get the challenge_id

    # Create automatic invitation for creator
    creator_invitation = ChallengeInvitation(
        challenge_id=new_challenge.challenge_id,
        sender_id=current_user_id,
        receiver_id=current_user_id,
        status=InvitationStatus.ACCEPTED,
        responded_at=datetime.now()
    )
    session.add(creator_invitation)
    
    session.commit()
    session.refresh(new_challenge)
    return new_challenge


class ChallengeInviteCreate(BaseModel):
    challenge_id: int
    receiver_ids: List[int]

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

        await notification_service.send_challenge_invite(
            db=session,
            user_id=receiver.user_id,
            sender_name=sender.display_name,
            challenge_title=challenge.title,
            challenge_id=challenge.challenge_id,
            invitation_id=invitation.invitation_id
        )

    session.commit()
    return {"message": f"Sent {len(invitations)} invitations"}


class ChallengeInviteAction(BaseModel):
    invitation_id: int

@router.put("/accept")
async def accept_challenge(
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
    
    # Get accepter info for notification
    accepter = session.get(User, current_user_id)
    
    invitation.status = InvitationStatus.ACCEPTED
    invitation.responded_at = datetime.now()
    session.add(invitation)
    
    # Send notification to challenge creator
    await notification_service.send_challenge_accept(
        db=session,
        user_id=challenge.creator_id,
        accepter_name=accepter.display_name,
        challenge_title=challenge.title,
        challenge_id=challenge.challenge_id
    )
    
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


class ChallengeCompletionStatus(str, Enum):
    COMPLETED = "completed"
    NOT_COMPLETED = "not_completed"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"

class SimpleChallengeResponse(ChallengePublic):
    has_new_submissions: bool
    completion_status: ChallengeCompletionStatus

class ChallengesListResponse(BaseModel):
    owned_challenges: List[SimpleChallengeResponse]
    participating_challenges: List[SimpleChallengeResponse]
    invitations: List[SimpleInviteResponse]

@router.get("/list", response_model=ChallengesListResponse)
def get_my_challenges(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get all challenges where user has accepted invitation (including owned ones)
    participating_statement = (
        select(Challenge, ChallengeSubmission.submission_id.label("submission_id"))
        .outerjoin(
            ChallengeSubmission,
            (ChallengeSubmission.challenge_id == Challenge.challenge_id) &
            (ChallengeSubmission.user_id == current_user_id)
        )
        .where(
            Challenge.challenge_id.in_(
                select(ChallengeInvitation.challenge_id)
                .where(
                    (ChallengeInvitation.receiver_id == current_user_id) &
                    (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
                )
            ) & 
            (Challenge.end_date > datetime.now())
        )
    )
    all_challenges = session.exec(participating_statement).all()

    # Split into owned and participating
    owned_challenges = []
    participating_challenges = []
    
    for challenge, submission_id in all_challenges:
        new_submissions_exist = has_new_submissions(session, challenge.challenge_id, current_user_id)

        # Determine completion status
        if submission_id is not None:
            completion_status = ChallengeCompletionStatus.COMPLETED
        elif challenge.end_date < datetime.now():
            completion_status = ChallengeCompletionStatus.NOT_COMPLETED
        elif challenge.start_date > datetime.now():
            completion_status = ChallengeCompletionStatus.PENDING
        else:
            completion_status = ChallengeCompletionStatus.IN_PROGRESS
        
        challenge_dict = {
            "challenge_id": challenge.challenge_id,
            "title": challenge.title,
            "emoji": challenge.emoji,
            "category": challenge.category,
            "end_date": challenge.end_date,
            "duration": challenge.duration,
            "activity_duration_minutes": challenge.activity_duration_minutes,
            "has_new_submissions": new_submissions_exist,
            "completion_status": completion_status
        }
        
        if challenge.creator_id == current_user_id:
            owned_challenges.append(challenge_dict)
        else:
            participating_challenges.append(challenge_dict)

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
            "activity_duration_minutes": challenge.activity_duration_minutes,
            "sender": sender
        })
    
    return {
        "owned_challenges": owned_challenges,
        "participating_challenges": participating_challenges,
        "invitations": invitations
    }


class UserChallengeHistoryResponse(ChallengePublic):
    has_submitted: bool
    has_new_submissions: bool

@router.get("/history", response_model=List[UserChallengeHistoryResponse])
def get_user_challenge_history(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get all challenges where user has an accepted invitation (including ones they created)
    challenges_query = (
        select(Challenge, User, ChallengeSubmission)
        .join(User, User.user_id == Challenge.creator_id)
        .join(
            ChallengeInvitation,
            (ChallengeInvitation.challenge_id == Challenge.challenge_id) &
            (ChallengeInvitation.receiver_id == current_user_id) &
            (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
        )
        .outerjoin(
            ChallengeSubmission,
            (ChallengeSubmission.challenge_id == Challenge.challenge_id) &
            (ChallengeSubmission.user_id == current_user_id)
        )
        .where(Challenge.end_date < datetime.now(timezone.utc))  # Only get challenges that have ended
        .order_by(Challenge.created_at.desc())
    )
    challenges = session.exec(challenges_query).all()
    
    result = []
    for challenge, creator, submission in challenges:
        # Check for new submissions
        new_submissions_exist = has_new_submissions(session, challenge.challenge_id, current_user_id)
        
        result.append({
            **challenge.model_dump(),
            "creator": creator,
            "has_submitted": submission is not None,
            "has_new_submissions": new_submissions_exist
        })
    
    return result


class RemoveParticipantRequest(BaseModel):
    challenge_id: int
    participant_id: int

@router.post("/remove-participant")
def remove_participant(
    request: RemoveParticipantRequest,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get challenge and verify ownership
    challenge = session.get(Challenge, request.challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="Only the challenge creator can remove participants")
    
    if challenge.status != ChallengeStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Can only modify active challenges")

    # Get the invitation
    invitation = session.exec(
        select(ChallengeInvitation)
        .where(
            (ChallengeInvitation.challenge_id == request.challenge_id) &
            (ChallengeInvitation.receiver_id == request.participant_id) &
            (ChallengeInvitation.status == InvitationStatus.ACCEPTED)
        )
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Participant not found in this challenge")

    # Update invitation status
    invitation.status = InvitationStatus.DECLINED
    invitation.responded_at = datetime.now()
    session.add(invitation)

    # Delete their submission and submission views if they exist
    submission = session.exec(
        select(ChallengeSubmission)
        .where(
            (ChallengeSubmission.challenge_id == request.challenge_id) &
            (ChallengeSubmission.user_id == request.participant_id)
        )
    ).first()

    if submission:
        # Delete submission views
        session.exec(
            delete(SubmissionView)
            .where(SubmissionView.submission_id == submission.submission_id)
        )
        
        # Delete the photo from S3
        try:
            delete_file(extract_key_from_url(submission.photo_url))
        except Exception as e:
            print(f"Failed to delete S3 photo {submission.photo_url}: {e}")

        # Delete the submission
        session.delete(submission)

    session.commit()
    return {"message": "Participant removed successfully"}


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

    # Check if user has accepted invitation
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
    
    # Read the file contents before passing to upload_image
    file_content = await file.read()
    
    photo_url = await upload_image(
        file_content,  # Pass the bytes content instead of the file object
        folder=f"challenge-submissions/{challenge_id}",
        identifier=str(current_user_id),
        width=1080,
        height=1920
    )

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
        await notification_service.send_challenge_submission(
            db=session,
            user_id=participant.user_id,
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


class Participant(UserPublic):
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
    activity_duration_minutes: Optional[int]
    creator: Participant
    participants: List[Participant]
    has_new_submissions: bool
    user_status: UserChallengeStatus
    invitation_id: Optional[int] = None

@router.get("/{challenge_id}", response_model=ChallengeResponse)
def get_challenge_details(
    challenge_id: int,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Get all participants and their submissions in a single query
    participants_query = (
        select(
            User,
            ChallengeInvitation,
            ChallengeSubmission.submission_id.label("has_submitted")
        )
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

    is_participant = False
    creator = None
    participants = []
    user_status = None
    invitation_id = None
    for user, invitation, submission_id in participant_results:
        user_dict = {
            **user.model_dump(),
            "has_submitted": submission_id is not None
        }
        
        if user.user_id == challenge.creator_id:
            creator = user_dict
        else:
            participants.append(user_dict)
        
        if user.user_id == current_user_id:
            # Determine user status and invitation_id
            if submission_id:
                user_status = UserChallengeStatus.SUBMITTED
            elif challenge.creator_id == current_user_id:
                user_status = UserChallengeStatus.PARTICIPANT
            elif invitation.invitation_id:
                if invitation.status == InvitationStatus.ACCEPTED:
                    user_status = UserChallengeStatus.PARTICIPANT
                else:  # PENDING
                    user_status = UserChallengeStatus.INVITED
                    invitation_id = invitation.invitation_id

            is_participant = True

    if not is_participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this challenge")

    # Check for new submissions efficiently
    new_submissions_exist = has_new_submissions(session, challenge_id, current_user_id)

    return {
        **challenge.model_dump(),
        "creator": creator,
        "participants": participants,
        "has_new_submissions": new_submissions_exist,
        "user_status": user_status,
        "invitation_id": invitation_id
    }


class ChallengeTitleUpdate(BaseModel):
    title: str

@router.put("/{challenge_id}/title")
def update_challenge_title(
    challenge_id: int,
    update: ChallengeTitleUpdate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    """Update the title of a challenge. Only the creator can update the title."""
    
    # Get challenge and verify ownership
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="Only the challenge creator can update the title")
    
    if challenge.status != ChallengeStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Can only update active challenges")

    # Update title
    challenge.title = update.title
    session.add(challenge)
    session.commit()
    session.refresh(challenge)
    return challenge


class ChallengeDescriptionUpdate(BaseModel):
    description: Optional[str] = None

@router.put("/{challenge_id}/description")
def update_challenge_description(
    challenge_id: int,
    update: ChallengeDescriptionUpdate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    """Update the description of a challenge. Only the creator can update the description."""
    
    # Get challenge and verify ownership
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="Only the challenge creator can update the description")
    
    if challenge.status != ChallengeStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Can only update active challenges")

    # Update description
    challenge.description = update.description
    session.add(challenge)
    session.commit()
    session.refresh(challenge)
    return challenge


@router.delete("/{challenge_id}")
async def delete_challenge(
    challenge_id: int,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    """Delete a challenge and all its related data, including S3 photos. Only the creator can delete it."""
    
    # Get challenge and verify ownership
    challenge = session.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="Only the challenge creator can delete the challenge")

    # Get all submission photo URLs before deleting the records
    submissions = session.exec(
        select(ChallengeSubmission)
        .where(ChallengeSubmission.challenge_id == challenge_id)
    ).all()
    
    photo_urls = [submission.photo_url for submission in submissions]

    # Delete in correct order to handle foreign key constraints
    
    # 1. Delete submission views first
    session.exec(
        delete(SubmissionView)
        .where(
            SubmissionView.submission_id.in_(
                select(ChallengeSubmission.submission_id)
                .where(ChallengeSubmission.challenge_id == challenge_id)
            )
        )
    )
    
    # 2. Delete submissions
    session.exec(
        delete(ChallengeSubmission)
        .where(ChallengeSubmission.challenge_id == challenge_id)
    )
    
    # 3. Delete invitations
    session.exec(
        delete(ChallengeInvitation)
        .where(ChallengeInvitation.challenge_id == challenge_id)
    )
    
    # 4. Delete the challenge
    session.delete(challenge)
    session.commit()

    # After successful database deletion, delete the S3 photos
    for photo_url in photo_urls:
        try:
            delete_file(extract_key_from_url(photo_url))
        except Exception as e:
            print(f"Failed to delete S3 photo {photo_url}: {e}")
            # Continue with other deletions even if one fails
    
    return {"message": "Challenge and all related data deleted successfully"}