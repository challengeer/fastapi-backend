from fastapi import APIRouter, Depends
from sqlmodel import Session, select, and_, delete
from typing import List
from datetime import datetime, timedelta, timezone

from ..services.database import get_session
from ..models.user import User, UserPublic
from ..models.contact import Contact, ContactBatchCreate
from ..models.friendship import Friendship
from ..services.auth import get_current_user_id

router = APIRouter(
    prefix="/contacts",
    tags=["Contacts"]
)

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
    
    # If there are existing contacts, check if they're older than one week
    if existing_contacts:
        one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)
        if existing_contacts.created_at.replace(tzinfo=timezone.utc) > one_week_ago:
            return {"message": "Contacts were uploaded recently, skipping update"}
    
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
    # Get user's contacts
    user_contacts = session.exec(
        select(Contact.phone_number)
        .where(Contact.user_id == current_user_id)
    ).all()
    
    if not user_contacts:
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
    
    # Find users who have matching phone numbers in their contacts
    potential_friends = session.exec(
        select(User, Contact)
        .join(Contact, Contact.user_id == User.user_id)
        .where(
            and_(
                Contact.phone_number.in_(user_contacts),
                User.user_id != current_user_id,
                User.user_id.notin_(existing_friends)
            )
        )
    ).all()
    
    # Count mutual contacts for each potential friend
    recommendations = {}
    for user, contact in potential_friends:
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
    
    # Get all users who have this contact in their contacts
    contact_phone_numbers = [contact.phone_number for contact in user_contacts]
    
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
    for contact in user_contacts:
        # Base score starts at 1
        score = 1.0
        
        # Count how many users have this contact
        matching_users = [user for user, c in contact_users if c.phone_number == contact.phone_number]
        score += len(matching_users) * 0.5  # Each matching user adds 0.5 to the score
        
        # Add bonus for contacts that are already users
        if any(user.phone_number == contact.phone_number for user, _ in contact_users):
            score += 2.0
        
        contact_scores[contact.contact_id] = score
    
    # Sort contacts by interest score and limit to 50
    sorted_contacts = sorted(
        user_contacts,
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