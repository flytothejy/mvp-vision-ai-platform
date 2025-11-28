"""Invitation API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional

from app.db.database import get_db, get_user_db
from app.db.models import (
    User, Invitation, InvitationType, InvitationStatus, UserRole,
    Organization, Project, ProjectMember
)
# Phase 11.5: Dataset model removed (managed by Labeler)
from app.schemas.invitation import (
    InvitationCreate,
    InvitationResponse,
    InvitationInfoResponse,
    AcceptInvitationRequest,
    DeclineInvitationRequest,
    InvitationListResponse,
)
from app.utils.dependencies import get_current_active_user
from app.services.email_service import get_email_service
from app.core.security import get_password_hash

router = APIRouter(prefix="/invitations", tags=["invitations"])


# ==================== Public Endpoints ====================

@router.get("/{token}/info", response_model=InvitationInfoResponse)
def get_invitation_info(
    token: str,
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db)
):
    """
    Get invitation information by token (public endpoint).

    Used by invitation page to display invitation details before signup.

    Phase 11: Uses 2-DB pattern - User DB for invitations/users/orgs, Platform DB for projects/datasets.
    """
    # Get invitation from User DB
    invitation = user_db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.status == InvitationStatus.PENDING
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    # Check if expired
    if invitation.is_expired():
        invitation.status = InvitationStatus.EXPIRED
        user_db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")

    # Get entity name and organization info
    entity_name = ""
    organization_name = None

    if invitation.invitation_type == InvitationType.ORGANIZATION:
        # Organization is in User DB
        org = user_db.query(Organization).filter(Organization.id == invitation.organization_id).first()
        entity_name = org.name if org else "Organization"

    elif invitation.invitation_type == InvitationType.PROJECT:
        # Project is in Platform DB
        project = db.query(Project).filter(Project.id == invitation.project_id).first()
        if project:
            entity_name = project.name
            # Organization is in User DB (if project has organization_id)
            if hasattr(project, 'organization_id') and project.organization_id:
                org = user_db.query(Organization).filter(Organization.id == project.organization_id).first()
                if org:
                    organization_name = org.name

    elif invitation.invitation_type == InvitationType.DATASET:
        # Phase 11.5: Dataset managed by Labeler, show ID only
        # TODO: Query Labeler API for dataset name
        entity_name = f"Dataset ({invitation.dataset_id[:8]}...)" if invitation.dataset_id else "Dataset"

    # Get inviter name from User DB
    inviter = user_db.query(User).filter(User.id == invitation.inviter_id).first()
    inviter_name = inviter.full_name or inviter.email if inviter else "Unknown"

    return InvitationInfoResponse(
        token=invitation.token,
        invitation_type=invitation.invitation_type,
        inviter_name=inviter_name,
        invitee_email=invitation.invitee_email,
        invitee_role=invitation.invitee_role,
        entity_name=entity_name,
        organization_name=organization_name,
        message=invitation.message,
        expires_at=invitation.expires_at,
        is_expired=invitation.is_expired()
    )


@router.post("/accept", response_model=dict)
def accept_invitation(
    request: AcceptInvitationRequest,
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db)
):
    """
    Accept an invitation and create user account if needed.

    If user already exists with this email, just add them to the entity.
    If user doesn't exist, create new account and add to entity.
    """
    # Get invitation
    invitation = db.query(Invitation).filter(
        Invitation.token == request.token,
        Invitation.status == InvitationStatus.PENDING
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    # Check if expired
    if invitation.is_expired():
        invitation.status = InvitationStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")

    # Check if user already exists
    existing_user = user_db.query(User).filter(User.email == invitation.invitee_email).first()

    if existing_user:
        # User exists, just add to entity
        user = existing_user
    else:
        # Create new user
        if not request.password:
            raise HTTPException(status_code=400, detail="Password required for new account")

        # Determine organization based on invitation type
        organization_id = None
        if invitation.invitation_type == InvitationType.ORGANIZATION:
            organization_id = invitation.organization_id
        elif invitation.invitation_type == InvitationType.PROJECT:
            project = db.query(Project).filter(Project.id == invitation.project_id).first()
            if project:
                organization_id = project.organization_id
        elif invitation.invitation_type == InvitationType.DATASET:
            # Phase 11.5: Dataset managed by Labeler
            # TODO: Query Labeler API for dataset owner and organization
            pass  # organization_id stays None for now

        # Generate avatar name
        import random
        AVATAR_ADJECTIVES = ['happy', 'brave', 'clever', 'wise', 'swift']
        AVATAR_NOUNS = ['panda', 'tiger', 'eagle', 'dolphin', 'fox']
        avatar_name = f"{random.choice(AVATAR_ADJECTIVES)}-{random.choice(AVATAR_NOUNS)}-{random.randint(100, 999)}"

        user = User(
            email=invitation.invitee_email,
            hashed_password=get_password_hash(request.password),
            full_name=request.full_name,
            phone_number=request.phone_number,
            department=request.department,
            organization_id=organization_id,
            system_role=invitation.invitee_role,
            avatar_name=avatar_name,
            is_active=True
        )
        db.add(user)
        db.flush()  # Get user.id

    # Add user to entity based on invitation type
    if invitation.invitation_type == InvitationType.PROJECT:
        # Check if already a member
        existing_member = db.query(ProjectMember).filter(
            ProjectMember.project_id == invitation.project_id,
            ProjectMember.user_id == user.id
        ).first()

        if not existing_member:
            member = ProjectMember(
                project_id=invitation.project_id,
                user_id=user.id,
                role=invitation.invitee_role.value,  # Use role from invitation
                joined_at=datetime.utcnow()
            )
            db.add(member)

    # Update invitation status
    invitation.status = InvitationStatus.ACCEPTED
    invitation.invitee_id = user.id
    invitation.accepted_at = datetime.utcnow()

    db.commit()

    return {
        "message": "Invitation accepted successfully",
        "user_id": user.id,
        "email": user.email,
        "redirect_to": "/login" if existing_user else "/login?registered=true"
    }


@router.post("/decline")
def decline_invitation(
    request: DeclineInvitationRequest,
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db)
):
    """
    Decline an invitation.
    """
    invitation = db.query(Invitation).filter(
        Invitation.token == request.token,
        Invitation.status == InvitationStatus.PENDING
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already processed")

    invitation.status = InvitationStatus.DECLINED
    db.commit()

    return {"message": "Invitation declined"}


# ==================== Authenticated Endpoints ====================

@router.get("", response_model=InvitationListResponse)
def list_my_invitations(
    status: Optional[InvitationStatus] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    List invitations sent by the current user.
    """
    query = db.query(Invitation).filter(Invitation.inviter_id == current_user.id)

    if status:
        query = query.filter(Invitation.status == status)

    total = query.count()
    invitations = query.order_by(Invitation.created_at.desc()).offset(skip).limit(limit).all()

    return InvitationListResponse(
        invitations=invitations,
        total=total,
        skip=skip,
        limit=limit
    )


@router.delete("/{invitation_id}")
def cancel_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Cancel an invitation (set status to CANCELLED).

    Only the inviter can cancel their own invitations.
    """
    invitation = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.inviter_id == current_user.id
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel invitation with status: {invitation.status.value}"
        )

    invitation.status = InvitationStatus.CANCELLED
    db.commit()

    return {"message": "Invitation cancelled successfully"}


# ==================== Helper function for creating invitations ====================

def create_invitation(
    db: Session,
    inviter: User,
    invitee_email: str,
    invitation_type: InvitationType,
    entity_id: int | str,
    invitee_role: UserRole,
    message: Optional[str] = None,
    expires_in_days: int = 7
) -> Invitation:
    """
    Helper function to create an invitation and send email.

    Args:
        db: Database session
        inviter: User sending the invitation
        invitee_email: Email of person being invited
        invitation_type: Type of invitation
        entity_id: ID of entity (organization_id, project_id, or dataset_id)
        invitee_role: Role to assign
        message: Optional personal message
        expires_in_days: Days until expiration (default 7)

    Returns:
        Created Invitation object
    """
    # Generate token
    token = Invitation.generate_token()

    # Calculate expiration
    expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

    # Determine which ID field to set
    kwargs = {
        "token": token,
        "invitation_type": invitation_type,
        "inviter_id": inviter.id,
        "invitee_email": invitee_email,
        "invitee_role": invitee_role,
        "message": message,
        "expires_at": expires_at,
        "status": InvitationStatus.PENDING
    }

    # Set the appropriate entity ID
    if invitation_type == InvitationType.ORGANIZATION:
        kwargs["organization_id"] = entity_id
    elif invitation_type == InvitationType.PROJECT:
        kwargs["project_id"] = entity_id
    elif invitation_type == InvitationType.DATASET:
        kwargs["dataset_id"] = entity_id

    invitation = Invitation(**kwargs)
    db.add(invitation)
    db.flush()  # Get invitation.id

    # Send email (async in real implementation)
    email_service = get_email_service()

    # Get entity name for email
    entity_name = ""
    if invitation_type == InvitationType.ORGANIZATION:
        org = db.query(Organization).filter(Organization.id == entity_id).first()
        entity_name = org.name if org else "Organization"
    elif invitation_type == InvitationType.PROJECT:
        project = db.query(Project).filter(Project.id == entity_id).first()
        entity_name = project.name if project else "Project"
    elif invitation_type == InvitationType.DATASET:
        # Phase 11.5: Dataset managed by Labeler
        # TODO: Query Labeler API for dataset name
        entity_name = f"Dataset ({entity_id[:8]}...)" if entity_id else "Dataset"

    inviter_name = inviter.full_name or inviter.email

    email_service.send_invitation_email(
        to_email=invitee_email,
        token=token,
        inviter_name=inviter_name,
        entity_type=invitation_type.value,
        entity_name=entity_name,
        message=message
    )

    return invitation
