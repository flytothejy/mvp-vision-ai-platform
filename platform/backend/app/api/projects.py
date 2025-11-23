"""Projects API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.db.database import get_db, get_user_db
from app.db.models import Project, TrainingJob, User, ProjectMember, InvitationType, UserRole
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectWithExperimentsResponse,
)
from app.utils.dependencies import get_current_active_user
from app.api.invitations import create_invitation
from pydantic import BaseModel, EmailStr

router = APIRouter(tags=["projects"])


def check_project_access(project_id: int, user_id: int, db: Session) -> bool:
    """Check if user has access to project (owner or member)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return False

    # Check if owner
    if project.user_id == user_id:
        return True

    # Check if member
    is_member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id
    ).first()

    return is_member is not None


class ProjectMemberResponse(BaseModel):
    """Schema for project member response."""
    user_id: int
    email: str
    full_name: str | None
    role: str
    joined_at: str
    is_owner: bool
    badge_color: str | None

    class Config:
        from_attributes = True


class MemberInviteRequest(BaseModel):
    """Schema for inviting a member to project."""
    email: EmailStr
    role: str = "member"  # member, viewer, etc.
    message: str | None = None  # Optional personal message


@router.post("", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new project."""

    # Check if project with same name already exists for this user
    existing = db.query(Project).filter(
        Project.name == project.name,
        Project.user_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project with this name already exists")

    db_project = Project(
        name=project.name,
        description=project.description,
        task_type=project.task_type,
        user_id=current_user.id,  # Set the owner
    )

    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    return db_project


@router.get("", response_model=List[ProjectWithExperimentsResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """List all projects owned by or shared with the current user with experiment counts."""

    # Get owned projects
    owned_projects = (
        db.query(
            Project,
            func.count(TrainingJob.id).label("experiment_count")
        )
        .filter(Project.user_id == current_user.id)
        .outerjoin(TrainingJob, TrainingJob.project_id == Project.id)
        .group_by(Project.id)
        .all()
    )

    # Get projects where user is a member (with role)
    member_projects = (
        db.query(
            Project,
            func.count(TrainingJob.id).label("experiment_count"),
            ProjectMember.role
        )
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(ProjectMember.user_id == current_user.id)
        .outerjoin(TrainingJob, TrainingJob.project_id == Project.id)
        .group_by(Project.id, ProjectMember.role)
        .all()
    )

    # Format owned projects
    result = []
    seen_ids = set()

    for project, exp_count in owned_projects:
        if project.id not in seen_ids:
            seen_ids.add(project.id)
            result.append(
                ProjectWithExperimentsResponse(
                    id=project.id,
                    name=project.name,
                    description=project.description,
                    task_type=project.task_type,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                    experiment_count=exp_count,
                    user_role="owner"
                )
            )

    # Format member projects
    for project, exp_count, role in member_projects:
        if project.id not in seen_ids:
            seen_ids.add(project.id)
            result.append(
                ProjectWithExperimentsResponse(
                    id=project.id,
                    name=project.name,
                    description=project.description,
                    task_type=project.task_type,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                    experiment_count=exp_count,
                    user_role=role  # Use actual role from ProjectMember
                )
            )

    return result


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get a specific project by ID."""

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission (owner or member)
    if not check_project_access(project_id, current_user.id, db):
        raise HTTPException(status_code=403, detail="Not authorized to access this project")

    return project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update a project."""

    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission
    if db_project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this project")

    # Update fields if provided
    if project_update.name is not None:
        # Check if new name conflicts with existing project for this user
        existing = db.query(Project).filter(
            Project.name == project_update.name,
            Project.id != project_id,
            Project.user_id == current_user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Project with this name already exists")
        db_project.name = project_update.name

    if project_update.description is not None:
        db_project.description = project_update.description

    if project_update.task_type is not None:
        db_project.task_type = project_update.task_type

    db.commit()
    db.refresh(db_project)

    return db_project


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete a project and all its experiments."""

    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission
    if db_project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this project")

    # Prevent deletion of default "Uncategorized" project
    if db_project.name == "Uncategorized":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the default 'Uncategorized' project"
        )

    # Get experiment count
    exp_count = db.query(TrainingJob).filter(TrainingJob.project_id == project_id).count()

    # Delete project (cascade will delete experiments)
    db.delete(db_project)
    db.commit()

    return {
        "message": f"Project '{db_project.name}' deleted successfully",
        "deleted_experiments": exp_count
    }


@router.get("/{project_id}/experiments")
def get_project_experiments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all experiments for a specific project."""

    # Check if project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission (owner or member)
    if not check_project_access(project_id, current_user.id, db):
        raise HTTPException(status_code=403, detail="Not authorized to access this project")

    # Get all experiments for this project
    experiments = (
        db.query(TrainingJob)
        .filter(TrainingJob.project_id == project_id)
        .order_by(TrainingJob.created_at.desc())
        .all()
    )

    from app.schemas.training import TrainingJobResponse
    return [TrainingJobResponse.from_orm(exp) for exp in experiments]


@router.get("/{project_id}/members", response_model=List[ProjectMemberResponse])
def get_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all members of a project."""

    # Check if project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission (owner or member)
    if not check_project_access(project_id, current_user.id, db):
        raise HTTPException(status_code=403, detail="Not authorized to access this project")

    # Get owner
    members = []
    if project.user_id:
        owner = db.query(User).filter(User.id == project.user_id).first()
        if owner:
            members.append({
                "user_id": owner.id,
                "email": owner.email,
                "full_name": owner.full_name,
                "role": "owner",
                "joined_at": project.created_at.isoformat(),
                "is_owner": True,
                "badge_color": owner.badge_color
            })

    # Get other members
    project_members = (
        db.query(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == project_id)
        .all()
    )

    for member, user in project_members:
        members.append({
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": member.role,
            "joined_at": member.joined_at.isoformat(),
            "is_owner": False,
            "badge_color": user.badge_color
        })

    return members


@router.post("/{project_id}/members")
def invite_project_member(
    project_id: int,
    invite: MemberInviteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Invite a user to join the project.

    - If user exists: Add directly as ProjectMember
    - If user doesn't exist: Create Invitation and send email
    """

    # Check if project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission - only owner can invite
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only project owner can invite members")

    # Map role string to UserRole enum (default to GUEST)
    role_mapping = {
        "owner": UserRole.ADMIN,
        "admin": UserRole.ADMIN,
        "manager": UserRole.MANAGER,
        "engineer_ii": UserRole.ENGINEER_II,
        "engineer_i": UserRole.ENGINEER_I,
        "engineer": UserRole.ENGINEER_I,
        "member": UserRole.ENGINEER_I,
        "viewer": UserRole.GUEST,
        "guest": UserRole.GUEST
    }
    user_role = role_mapping.get(invite.role.lower(), UserRole.GUEST)

    # Find user by email
    user = db.query(User).filter(User.email == invite.email).first()

    if user:
        # User exists - Add directly as ProjectMember

        # Check if user is already the owner
        if user.id == project.user_id:
            raise HTTPException(status_code=400, detail="User is already the project owner")

        # Check if user is already a member
        existing_member = db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id
        ).first()
        if existing_member:
            raise HTTPException(status_code=400, detail="User is already a member of this project")

        # Create membership
        from datetime import datetime
        new_member = ProjectMember(
            project_id=project_id,
            user_id=user.id,
            role=invite.role,
            invited_by=current_user.id,
            joined_at=datetime.utcnow()
        )

        db.add(new_member)
        db.commit()
        db.refresh(new_member)

        return {
            "message": "Member added successfully",
            "user_id": user.id,
            "email": user.email,
            "role": invite.role,
            "method": "direct_add"
        }

    else:
        # User doesn't exist - Create Invitation and send email

        # Check if there's already a pending invitation for this email
        from app.db.models import Invitation, InvitationStatus
        existing_invitation = db.query(Invitation).filter(
            Invitation.project_id == project_id,
            Invitation.invitee_email == invite.email,
            Invitation.status == InvitationStatus.PENDING
        ).first()

        if existing_invitation and not existing_invitation.is_expired():
            raise HTTPException(
                status_code=400,
                detail="A pending invitation already exists for this email"
            )

        # Create invitation
        invitation = create_invitation(
            db=db,
            inviter=current_user,
            invitee_email=invite.email,
            invitation_type=InvitationType.PROJECT,
            entity_id=project_id,
            invitee_role=user_role,
            message=invite.message,
            expires_in_days=7
        )

        db.commit()

        return {
            "message": "Invitation sent successfully",
            "invitee_email": invite.email,
            "invitation_id": invitation.id,
            "token": invitation.token,
            "expires_at": invitation.expires_at.isoformat(),
            "role": invite.role,
            "method": "invitation_email"
        }


@router.delete("/{project_id}/members/{user_id}")
def remove_project_member(
    project_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Remove a member from the project."""

    # Check if project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission - only owner can remove members
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only project owner can remove members")

    # Cannot remove owner
    if user_id == project.user_id:
        raise HTTPException(status_code=400, detail="Cannot remove project owner")

    # Find membership
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    db.delete(member)
    db.commit()

    return {"message": "Member removed successfully", "user_id": user_id}
