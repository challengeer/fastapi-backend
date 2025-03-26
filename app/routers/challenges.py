from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
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

class SimpleChallengeResponse(ChallengePublic):
    has_new_submissions: bool

class SimpleInviteResponse(ChallengePublic):
    invitation_id: int
    sender: UserPublic

class ChallengesListResponse(BaseModel):
    owned_challenges: List[SimpleChallengeResponse]
    participating_challenges: List[SimpleChallengeResponse]
    invitations: List[SimpleInviteResponse]


class ChallengeCreate(BaseModel):
    title: str
    description: Optional[str] = None
    emoji: Optional[str] = "🎯"
    category: str

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

        # Send notification if receiver has FCM token
        if receiver.fcm_token:
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


@router.get("/list", response_model=ChallengesListResponse)
def get_my_challenges(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get owned challenges
    owned_statement = (
        select(Challenge)
        .where(
            (Challenge.creator_id == current_user_id) &
            (Challenge.end_date > datetime.now())
        )
    )
    owned_results = session.exec(owned_statement).all()

    # Get participating challenges (where user accepted invitation)
    participating_statement = (
        select(Challenge)
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
    participating_results = session.exec(participating_statement).all()

    # Process owned challenges
    owned_challenges = []
    for challenge in owned_results:
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
        
        owned_challenges.append({
            "challenge_id": challenge.challenge_id,
            "title": challenge.title,
            "emoji": challenge.emoji,
            "category": challenge.category,
            "end_date": challenge.end_date,
            "has_new_submissions": new_submissions_exist
        })

    # Process participating challenges
    participating_challenges = []
    for challenge in participating_results:
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
        
        participating_challenges.append({
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
        "owned_challenges": owned_challenges,
        "participating_challenges": participating_challenges,
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
    
    photo_url = await upload_image(
        file.file,
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
        if participant.fcm_token:
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
    # Get challenge details with creator info and current user's status in one query
    statement = (
        select(
            Challenge,
            User,
            ChallengeInvitation,
            ChallengeSubmission.submission_id.label("user_submission_id")
        )
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
    
    challenge, creator, user_invitation, user_submission_id = result

    # Get creator's submission status separately
    creator_submission = session.exec(
        select(ChallengeSubmission.submission_id)
        .where(
            (ChallengeSubmission.challenge_id == challenge_id) &
            (ChallengeSubmission.user_id == challenge.creator_id)
        )
    ).first()

    # Check participation status and authorization
    is_creator = challenge.creator_id == current_user_id
    if not (is_creator or (user_invitation and user_invitation.status in [InvitationStatus.ACCEPTED, InvitationStatus.PENDING])):
        raise HTTPException(status_code=403, detail="You are not a participant in this challenge")

    # Get all participants and their submissions in a single query
    participants_query = (
        select(
            User,
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

    # Determine user status and invitation_id
    if user_submission_id:
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

    # Check for new submissions efficiently
    new_submissions_exist = session.exec(
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

    return {
        **challenge.model_dump(),
        "creator": {
            **creator.model_dump(),
            "has_submitted": creator_submission is not None
        },
        "participants": [
            {
                **user.model_dump(),
                "has_submitted": submission_id is not None
            }
            for user, submission_id in participant_results
        ],
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
        select(SubmissionView)
        .join(ChallengeSubmission, ChallengeSubmission.submission_id == SubmissionView.submission_id)
        .where(ChallengeSubmission.challenge_id == challenge_id)
    ).delete()
    
    # 2. Delete submissions
    session.exec(
        select(ChallengeSubmission)
        .where(ChallengeSubmission.challenge_id == challenge_id)
    ).delete()
    
    # 3. Delete invitations
    session.exec(
        select(ChallengeInvitation)
        .where(ChallengeInvitation.challenge_id == challenge_id)
    ).delete()
    
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