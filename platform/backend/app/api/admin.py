"""Admin API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel

from app.db.database import get_db, get_user_db
from app.db.models import Project, TrainingJob, User
from app.schemas.project import ProjectResponse, ProjectUpdate
from app.schemas.user import UserResponse
from app.utils.dependencies import get_current_active_user

router = APIRouter(tags=["admin"])


class UserRoleUpdate(BaseModel):
    """Schema for updating user role."""
    system_role: str


class AdminUserUpdate(BaseModel):
    """Schema for admin to update user info."""
    email: Optional[str] = None
    full_name: Optional[str] = None
    company: Optional[str] = None
    division: Optional[str] = None
    department: Optional[str] = None
    phone_number: Optional[str] = None


class AdminProjectUpdate(BaseModel):
    """Schema for admin to update any project."""
    name: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    user_id: Optional[int] = None  # Allow admin to change owner


def require_admin(current_user: User = Depends(get_current_active_user)):
    """Dependency to check if user is admin."""
    if current_user.system_role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required"
        )
    return current_user


def require_admin_or_manager(current_user: User = Depends(get_current_active_user)):
    """Dependency to check if user is admin or manager."""
    if current_user.system_role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Admin or Manager privileges required"
        )
    return current_user


@router.get("/projects")
def list_all_projects(
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(require_admin)
):
    """List all projects in the system (admin only).

    Phase 11: Uses 2-DB pattern - Platform DB for projects, User DB for owners.
    """

    # Query all projects with experiment counts from Platform DB
    projects_with_counts = (
        db.query(
            Project,
            func.count(TrainingJob.id).label("experiment_count")
        )
        .outerjoin(TrainingJob, TrainingJob.project_id == Project.id)
        .group_by(Project.id)
        .all()
    )

    # Get all unique user IDs
    user_ids = list(set([p.user_id for p, _ in projects_with_counts if p.user_id]))

    # Fetch users from User DB
    users = {}
    if user_ids:
        users_list = user_db.query(User).filter(User.id.in_(user_ids)).all()
        users = {u.id: u for u in users_list}

    # Format response
    result = []
    for project, exp_count in projects_with_counts:
        owner = users.get(project.user_id)
        result.append({
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "task_type": project.task_type,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "experiment_count": exp_count,
            "owner_id": project.user_id,
            "owner_name": owner.full_name if owner else None,
            "owner_email": owner.email if owner else None,
        })

    return result


@router.get("/users")
def list_all_users(
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """List all users in the system (admin or manager).

    Phase 11: Uses 2-DB pattern - User DB for users, Platform DB for project counts.
    """

    # Query all users from User DB
    query = user_db.query(User)

    # If user is manager, exclude other managers and admins
    if current_user.system_role == "manager":
        query = query.filter(User.system_role.notin_(["manager", "admin"]))

    users = query.all()

    # Get project counts from Platform DB
    project_counts_query = (
        db.query(
            Project.user_id,
            func.count(Project.id).label("count")
        )
        .group_by(Project.user_id)
        .all()
    )
    project_counts = {user_id: count for user_id, count in project_counts_query}

    # Format response
    result = []
    for user in users:
        result.append({
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "company": user.company,
            "company_custom": user.company_custom,
            "division": user.division,
            "division_custom": user.division_custom,
            "department": user.department,
            "phone_number": user.phone_number,
            "system_role": user.system_role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "project_count": project_counts.get(user.id, 0),
        })

    return result


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    user_update: AdminUserUpdate,
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Update a user's information (admin or manager).

    Phase 11: Uses User DB only.
    """

    # Get user from User DB
    user = user_db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update fields if provided
    if user_update.email is not None:
        # Check if email is already taken by another user
        existing_user = user_db.query(User).filter(User.email == user_update.email, User.id != user_id).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = user_update.email

    if user_update.full_name is not None:
        user.full_name = user_update.full_name
    if user_update.company is not None:
        # Store in company_custom for user-entered values
        user.company_custom = user_update.company
    if user_update.division is not None:
        # Store in division_custom for user-entered values
        user.division_custom = user_update.division
    if user_update.department is not None:
        user.department = user_update.department
    if user_update.phone_number is not None:
        user.phone_number = user_update.phone_number

    user_db.commit()
    user_db.refresh(user)

    return {
        "message": "User updated successfully",
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name
    }


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    role_update: UserRoleUpdate,
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Update a user's system role (admin or manager).

    Phase 11: Uses User DB only.
    """

    # Validate role
    valid_roles = ["guest", "standard_engineer", "advanced_engineer", "manager", "admin"]
    if role_update.system_role not in valid_roles:
        raise HTTPException(status_code=400, detail="Invalid role")

    # If user is manager, they cannot set roles to manager or admin
    if current_user.system_role == "manager" and role_update.system_role in ["manager", "admin"]:
        raise HTTPException(status_code=403, detail="Managers cannot assign manager or admin roles")

    # Get user from User DB
    user = user_db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent self-demotion
    if user.id == current_user.id and role_update.system_role not in ["admin", "manager"]:
        raise HTTPException(status_code=400, detail="Cannot demote yourself")

    # Update role
    user.system_role = role_update.system_role
    user_db.commit()
    user_db.refresh(user)

    return {"message": "Role updated successfully", "user_id": user.id, "new_role": user.system_role}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(require_admin)
):
    """Delete a user (admin only). Fails if user has projects.

    Phase 11: Uses 2-DB pattern - User DB for user, Platform DB for project check.
    """

    # Get user from User DB
    user = user_db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent self-deletion
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    # Check if user has projects in Platform DB
    project_count = db.query(Project).filter(Project.user_id == user_id).count()
    if project_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete user with {project_count} project(s). Delete or reassign projects first."
        )

    # Delete user from User DB
    user_db.delete(user)
    user_db.commit()

    return {"message": "User deleted successfully", "user_id": user_id}


@router.put("/projects/{project_id}")
def update_project(
    project_id: int,
    project_update: AdminProjectUpdate,
    db: Session = Depends(get_db),
    user_db: Session = Depends(get_user_db),
    current_user: User = Depends(require_admin)
):
    """Update a project (admin only).

    Phase 11: Uses 2-DB pattern - Platform DB for project, User DB for owner verification.
    """

    # Get project from Platform DB
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update fields
    if project_update.name is not None:
        project.name = project_update.name
    if project_update.description is not None:
        project.description = project_update.description
    if project_update.task_type is not None:
        project.task_type = project_update.task_type
    if project_update.user_id is not None:
        # Verify new owner exists in User DB
        new_owner = user_db.query(User).filter(User.id == project_update.user_id).first()
        if not new_owner:
            raise HTTPException(status_code=404, detail="New owner user not found")
        project.user_id = project_update.user_id

    db.commit()
    db.refresh(project)

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "task_type": project.task_type,
        "user_id": project.user_id,
        "updated_at": project.updated_at
    }


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a project and all its experiments (admin only)."""

    # Get project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get experiment count
    exp_count = db.query(TrainingJob).filter(TrainingJob.project_id == project_id).count()

    # Delete project (cascade will delete experiments)
    db.delete(project)
    db.commit()

    return {
        "message": f"Project '{project.name}' deleted successfully",
        "project_id": project_id,
        "deleted_experiments": exp_count
    }
