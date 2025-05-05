from fastapi import APIRouter, Depends
from sqlmodel import Session, select, and_, delete
from typing import List
from datetime import datetime, timedelta, timezone

from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.contact import Contact, ContactBatchCreate
from ..models.friendship import Friendship
from ..services.auth import get_current_user_id
from ..models.friend_request import FriendRequest, RequestStatus

# Constants
CONTACT_UPLOAD_INTERVAL = timedelta(weeks=1)

router = APIRouter(
    prefix="/contacts",
    tags=["Contacts"]
)

@router.get("/needs-upload")
async def check_contacts_upload(
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    existing_contacts = session.exec(
        select(Contact).where(Contact.user_id == current_user_id)
    ).first()
    
    if not existing_contacts:
        return {"needs_upload": True}
    
    last_upload_time = existing_contacts.created_at.replace(tzinfo=timezone.utc)
    cutoff_time = datetime.now(timezone.utc) - CONTACT_UPLOAD_INTERVAL
    
    return {"needs_upload": last_upload_time <= cutoff_time}

@router.post("/upload")
async def upload_contacts(
    contacts: ContactBatchCreate,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Check if there are any existing contacts
    existing_contacts = session.exec(
        select(Contact).where(Contact.user_id == current_user_id)
    ).first()
    
    # If there are existing contacts, check if they're older than the upload interval
    if existing_contacts:
        cutoff_time = datetime.now(timezone.utc) - CONTACT_UPLOAD_INTERVAL
        if existing_contacts.created_at.replace(tzinfo=timezone.utc) > cutoff_time:
            return {"message": "Contacts were uploaded recently, skipping upload"}
    
    # Delete existing contacts for the user
    session.exec(
        delete(Contact).where(Contact.user_id == current_user_id)
    )
    
    # Add new contacts
    for contact in contacts.contacts:
        new_contact = Contact(
            user_id=current_user_id,
            contact_name=contact.contact_name,
            phone_number=contact.phone_number
        )
        session.add(new_contact)
    
    session.commit()
    return {"message": "Contacts uploaded successfully"}


class RecommendedFriend(UserPublic):
    mutual_contacts: int = 0

@router.get("/recommendations", response_model=List[RecommendedFriend])
async def get_friend_recommendations(
    limit: int | None = None,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get current user's phone number
    current_user = session.exec(
        select(User).where(User.user_id == current_user_id)
    ).first()
    
    if not current_user:
        return []
    
    # Get user's existing friends
    existing_friends = session.exec(
        select(User.user_id)
        .join(
            Friendship,
            (Friendship.user2_id == User.user_id) & (Friendship.user1_id == current_user_id) |
            (Friendship.user1_id == User.user_id) & (Friendship.user2_id == current_user_id)
        )
    ).all()
    
    # Get users with pending friend requests
    pending_requests = session.exec(
        select(User.user_id)
        .join(
            FriendRequest,
            ((FriendRequest.sender_id == User.user_id) & (FriendRequest.receiver_id == current_user_id)) |
            ((FriendRequest.receiver_id == User.user_id) & (FriendRequest.sender_id == current_user_id))
        )
        .where(FriendRequest.status == RequestStatus.PENDING)
    ).all()
    
    recommendations = {}
    
    # Approach 1: Find users who have the current user's phone number in their contacts
    if current_user.phone_number:
        potential_friends_1 = session.exec(
            select(User, Contact)
            .join(Contact, Contact.user_id == User.user_id)
            .where(
                and_(
                    Contact.phone_number == current_user.phone_number,
                    User.user_id != current_user_id,
                    User.user_id.notin_(existing_friends),
                    User.user_id.notin_(pending_requests)
                )
            )
        ).all()
        
        for user, contact in potential_friends_1:
            if user.user_id not in recommendations:
                recommendations[user.user_id] = {
                    "user_id": user.user_id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "profile_picture": user.profile_picture,
                    "mutual_contacts": 1
                }
            else:
                recommendations[user.user_id]["mutual_contacts"] += 1
    
    # Approach 2: Find users based on current user's contacts
    user_contacts = session.exec(
        select(Contact.phone_number)
        .where(Contact.user_id == current_user_id)
    ).all()
    
    if user_contacts:
        potential_friends_2 = session.exec(
            select(User, Contact)
            .join(Contact, Contact.user_id == User.user_id)
            .where(
                and_(
                    Contact.phone_number.in_(user_contacts),
                    User.user_id != current_user_id,
                    User.user_id.notin_(existing_friends),
                    User.user_id.notin_(pending_requests)
                )
            )
        ).all()
        
        for user, contact in potential_friends_2:
            if user.user_id not in recommendations:
                recommendations[user.user_id] = {
                    "user_id": user.user_id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "profile_picture": user.profile_picture,
                    "mutual_contacts": 1
                }
            else:
                recommendations[user.user_id]["mutual_contacts"] += 1
    
    # Convert to list and sort by mutual contacts
    recommendations_list = list(recommendations.values())
    recommendations_list.sort(key=lambda x: x["mutual_contacts"], reverse=True)
    
    # Apply limit if specified
    if limit is not None:
        recommendations_list = recommendations_list[:limit]
    
    return recommendations_list

class ContactWithInterest(Contact):
    interest_score: float = 0

@router.get("/sorted-by-interest", response_model=List[ContactWithInterest])
async def get_sorted_contacts_by_interest(
    limit: int | None = None,
    session: Session = Depends(get_session),
    current_user_id: int = Depends(get_current_user_id)
):
    # Get all contacts for the current user
    user_contacts = session.exec(
        select(Contact)
        .where(Contact.user_id == current_user_id)
    ).all()
    
    if not user_contacts:
        return []
    
    # Get phone numbers from contacts
    contact_phone_numbers = [contact.phone_number for contact in user_contacts]
    
    # Check which of these phone numbers are registered users
    registered_phone_numbers = session.exec(
        select(User.phone_number)
        .where(
            and_(
                User.phone_number.in_(contact_phone_numbers),
                User.phone_number.isnot(None)
            )
        )
    ).all()
    
    # Filter out contacts that are already registered users
    filtered_contacts = [
        contact for contact in user_contacts 
        if contact.phone_number not in registered_phone_numbers
    ]
    
    if not filtered_contacts:
        return []
    
    # Find users who have matching phone numbers in their contacts
    contact_users = session.exec(
        select(User, Contact)
        .join(Contact, Contact.user_id == User.user_id)
        .where(
            and_(
                Contact.phone_number.in_(contact_phone_numbers),
                User.user_id != current_user_id
            )
        )
    ).all()
    
    # Calculate interest score for each contact
    contact_scores = {}
    for contact in filtered_contacts:
        # Base score starts at 1
        score = 1.0
        
        # Count how many users have this contact
        matching_users = [user for user, c in contact_users if c.phone_number == contact.phone_number]
        score += len(matching_users) * 0.5  # Each matching user adds 0.5 to the score
        
        contact_scores[contact.contact_id] = score
    
    # Sort contacts by interest score
    sorted_contacts = sorted(
        filtered_contacts,
        key=lambda x: contact_scores.get(x.contact_id, 0),
        reverse=True
    )

    # Apply limit if specified
    if limit is not None:
        sorted_contacts = sorted_contacts[:limit]
    
    # Add interest scores to the contacts
    result = []
    for contact in sorted_contacts:
        contact_with_score = ContactWithInterest(
            **contact.model_dump(),
            interest_score=contact_scores.get(contact.contact_id, 0)
        )
        result.append(contact_with_score)
    
    return result