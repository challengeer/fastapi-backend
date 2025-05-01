from fastapi import APIRouter, Depends
from sqlmodel import Session, select, and_, delete
from typing import List

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
    
    return recommendations_list 