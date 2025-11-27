"""Database models."""

import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship

from app.db.database import Base


class UserRole(str, enum.Enum):
    """5-tier user permission system"""
    ADMIN = "admin"              # All permissions
    MANAGER = "manager"          # Can grant permissions below manager
    ENGINEER_II = "engineer_ii"  # Advanced training features
    ENGINEER_I = "engineer_i"    # Basic training features
    GUEST = "guest"              # Limited: 1 project, 1 dataset, no collaboration


class InvitationType(str, enum.Enum):
    """Type of invitation"""
    ORGANIZATION = "organization"  # Invite to organization
    PROJECT = "project"            # Invite to project
    DATASET = "dataset"            # Invite to dataset


class InvitationStatus(str, enum.Enum):
    """Status of invitation"""
    PENDING = "pending"      # Invitation sent, awaiting response
    ACCEPTED = "accepted"    # Invitation accepted
    DECLINED = "declined"    # Invitation declined by invitee
    EXPIRED = "expired"      # Invitation expired
    CANCELLED = "cancelled"  # Invitation cancelled by inviter


class Organization(Base):
    """Organization model for multi-tenancy support.

    Organizations group users by company and division.
    Each organization has resource quotas and limits.
    """

    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # "Samsung Electronics - MX Division"
    company = Column(String(255), nullable=False, index=True)
    division = Column(String(255), nullable=True)

    # Resource quotas (nullable = unlimited)
    max_users = Column(Integer, nullable=True)
    max_storage_gb = Column(Integer, nullable=True)
    max_gpu_hours_per_month = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="organization")
    projects = relationship("Project", back_populates="organization")


class Invitation(Base):
    """Invitation model for user invitations to organizations, projects, or datasets.

    Supports inviting users via email. When accepted, the user is automatically
    added to the relevant entity with the specified role.
    """

    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)  # Unique invitation token

    # Invitation metadata
    invitation_type = Column(SQLEnum(InvitationType), nullable=False, index=True)
    status = Column(SQLEnum(InvitationStatus), nullable=False, default=InvitationStatus.PENDING, index=True)

    # Target entities (one of these will be set based on invitation_type)
    organization_id = Column(Integer, ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=True, index=True)
    dataset_id = Column(String(100), ForeignKey('datasets.id', ondelete='CASCADE'), nullable=True, index=True)

    # Invitation parties
    inviter_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    invitee_email = Column(String(255), nullable=False, index=True)  # Email of person being invited
    invitee_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)  # Set when accepted

    # Role to assign upon acceptance
    invitee_role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.GUEST)

    # Optional invitation message
    message = Column(Text, nullable=True)

    # Expiration
    expires_at = Column(DateTime, nullable=False)  # Invitation expiration datetime

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)

    # Relationships
    inviter = relationship("User", foreign_keys=[inviter_id], backref="sent_invitations")
    invitee = relationship("User", foreign_keys=[invitee_id], backref="received_invitations")
    organization = relationship("Organization")
    project = relationship("Project")
    dataset = relationship("Dataset")

    def is_expired(self) -> bool:
        """Check if invitation is expired."""
        return datetime.utcnow() > self.expires_at

    @classmethod
    def generate_token(cls) -> str:
        """Generate a unique invitation token."""
        import secrets
        return secrets.token_urlsafe(32)


class User(Base):
    """User model for authentication and authorization."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)

    # Organization info
    company = Column(String(100), nullable=True)
    company_custom = Column(String(255), nullable=True)
    division = Column(String(100), nullable=True)
    division_custom = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True)
    organization_id = Column(Integer, ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True, index=True)

    phone_number = Column(String(50), nullable=True)
    bio = Column(Text, nullable=True)

    # Role and permissions
    system_role = Column(
        SQLEnum(UserRole, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=UserRole.GUEST,
        index=True
    )
    is_active = Column(Boolean, nullable=False, default=True)

    # Avatar
    avatar_name = Column(String(100), nullable=True)  # "John D", "JD", etc.
    badge_color = Column(String(20), nullable=True)  # Avatar badge color

    # Password reset
    password_reset_token = Column(String(255), nullable=True, unique=True, index=True)
    password_reset_expires = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="users")
    owned_projects = relationship("Project", back_populates="owner", foreign_keys="[Project.user_id]")
    sessions = relationship("Session", back_populates="user")
    created_training_jobs = relationship("TrainingJob", back_populates="creator", foreign_keys="[TrainingJob.created_by]")
    project_memberships = relationship("ProjectMember", back_populates="user", foreign_keys="[ProjectMember.user_id]")
    invited_members = relationship("ProjectMember", back_populates="inviter", foreign_keys="[ProjectMember.invited_by]")

    def can_create_project(self) -> bool:
        """Check if user can create a new project"""
        if self.system_role in [UserRole.ADMIN, UserRole.MANAGER,
                                UserRole.ADVANCED_ENGINEER, UserRole.STANDARD_ENGINEER]:
            return True

        if self.system_role == UserRole.GUEST:
            # Check if user already has 1 project
            return len(self.owned_projects) < 1

        return False

    def can_create_dataset(self) -> bool:
        """Check if user can create a new dataset"""
        if self.system_role in [UserRole.ADMIN, UserRole.MANAGER,
                                UserRole.ADVANCED_ENGINEER, UserRole.STANDARD_ENGINEER]:
            return True

        if self.system_role == UserRole.GUEST:
            # Check if user already has 1 dataset
            owned_datasets = [d for d in getattr(self, 'owned_datasets', []) if d.owner_id == self.id]
            return len(owned_datasets) < 1

        return False

    def can_grant_role(self, target_role: UserRole) -> bool:
        """Check if user can grant a specific role"""
        if self.system_role == UserRole.ADMIN:
            return True

        if self.system_role == UserRole.MANAGER:
            # Manager can grant GUEST, STANDARD_ENGINEER, ADVANCED_ENGINEER
            return target_role in [UserRole.GUEST, UserRole.STANDARD_ENGINEER, UserRole.ADVANCED_ENGINEER]

        return False

    def has_advanced_features(self) -> bool:
        """Check if user can access advanced training features"""
        return self.system_role in [UserRole.ADMIN, UserRole.MANAGER, UserRole.ADVANCED_ENGINEER]


class ProjectMember(Base):
    """Project member model for collaboration."""

    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role = Column(String(20), nullable=False, default='member')
    invited_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_memberships", foreign_keys=[user_id])
    inviter = relationship("User", back_populates="invited_members", foreign_keys=[invited_by])


class Dataset(Base):
    """Dataset model for managing training data.

    Datasets can be public (accessible to everyone), private (owner only),
    or organization-wide. Platform sample datasets are simply public datasets
    with 'platform-sample' tag.
    """

    __tablename__ = "datasets"

    id = Column(String(100), primary_key=True, index=True)  # UUID or simple ID like "det-coco8"
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Ownership (nullable for public datasets without specific owner)
    owner_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)

    # Visibility and access control
    visibility = Column(String(20), nullable=False, default='private', index=True)  # 'public', 'private', 'organization'
    tags = Column(JSON, nullable=True)  # e.g., ['platform-sample', 'object-detection', 'coco']

    # Storage
    storage_path = Column(String(500), nullable=False)  # e.g., "datasets/det-coco8/" or "datasets/{uuid}/"
    storage_type = Column(String(20), nullable=False, default='minio')  # 'r2', 'minio', 's3', 'gcs' - auto-detected from env

    # Dataset metadata
    format = Column(String(50), nullable=False)  # 'dice', 'yolo', 'imagefolder', 'coco', 'pascal_voc'
    labeled = Column(Boolean, nullable=False, default=False)  # Whether dataset has annotation.json
    annotation_path = Column(String(500), nullable=True)  # Path to annotation.json in R2
    num_classes = Column(Integer, nullable=True)
    num_images = Column(Integer, nullable=False, default=0)
    class_names = Column(JSON, nullable=True)  # List of class names

    # Train/Val split configuration (cached from annotations.json)
    split_config = Column(JSON, nullable=True)  # {"method": "auto", "default_ratio": [0.8, 0.2], "seed": 42, "splits": {...}}

    # Versioning and snapshots
    is_snapshot = Column(Boolean, nullable=False, default=False, index=True)  # Is this a snapshot?
    parent_dataset_id = Column(String(100), ForeignKey('datasets.id', ondelete='CASCADE'), nullable=True, index=True)  # Parent if snapshot
    snapshot_created_at = Column(DateTime, nullable=True)  # When snapshot was created
    version_tag = Column(String(50), nullable=True)  # User-defined version tag (v1, v2, etc.)

    # Status and integrity
    status = Column(String(20), nullable=False, default='active')  # 'active', 'archived', 'deleted'
    integrity_status = Column(String(20), nullable=False, default='valid')  # 'valid', 'broken', 'repairing'

    # Change tracking
    version = Column(Integer, nullable=False, default=1)
    content_hash = Column(String(64), nullable=True)  # SHA256 hash of dataset content
    last_modified_at = Column(DateTime, nullable=True)  # When data was last modified

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = relationship("User", backref="owned_datasets", foreign_keys=[owner_id])
    permissions = relationship("DatasetPermission", back_populates="dataset", cascade="all, delete-orphan")
    training_jobs = relationship("TrainingJob", back_populates="dataset", foreign_keys="[TrainingJob.dataset_id]")

    # Snapshot relationships (self-referential)
    parent = relationship("Dataset", remote_side=[id], foreign_keys=[parent_dataset_id], backref="snapshots")
    snapshot_training_jobs = relationship("TrainingJob", back_populates="dataset_snapshot", foreign_keys="[TrainingJob.dataset_snapshot_id]")


class DatasetPermission(Base):
    """Dataset permission model for collaboration.

    Controls who can view, edit, or manage a dataset.
    Public datasets don't require permissions for viewing.
    """

    __tablename__ = "dataset_permissions"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(String(100), ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    role = Column(String(20), nullable=False, default='viewer')  # 'owner', 'editor', 'viewer'
    granted_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    granted_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    dataset = relationship("Dataset", back_populates="permissions")
    user = relationship("User", foreign_keys=[user_id], backref="dataset_permissions")
    grantor = relationship("User", foreign_keys=[granted_by])


class Project(Base):
    """Project model for organizing experiments."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    task_type = Column(String(50), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    organization_id = Column(Integer, ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="owned_projects", foreign_keys=[user_id])
    organization = relationship("Organization", back_populates="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="project", cascade="all, delete-orphan")
    training_jobs = relationship("TrainingJob", back_populates="project", cascade="all, delete-orphan")


class Experiment(Base):
    """Experiment model for organizing training runs.

    Experiments group related training jobs and integrate with MLflow.
    Each experiment corresponds to one MLflow experiment.
    """

    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)

    # Basic info
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True, default=list)  # ["baseline", "production", etc.]

    # MLflow integration
    mlflow_experiment_id = Column(String(100), nullable=True, unique=True, index=True)
    mlflow_experiment_name = Column(String(255), nullable=True)

    # Cached statistics (updated periodically)
    num_runs = Column(Integer, nullable=False, default=0)
    num_completed_runs = Column(Integer, nullable=False, default=0)
    best_metrics = Column(JSON, nullable=True)  # {"accuracy": 0.95, "loss": 0.05}

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="experiments")
    training_jobs = relationship("TrainingJob", back_populates="experiment", cascade="all, delete-orphan")
    stars = relationship("ExperimentStar", back_populates="experiment", cascade="all, delete-orphan")
    notes = relationship("ExperimentNote", back_populates="experiment", cascade="all, delete-orphan")


class ExperimentStar(Base):
    """User's starred experiments for quick access."""

    __tablename__ = "experiment_stars"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    starred_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    experiment = relationship("Experiment", back_populates="stars")
    user = relationship("User")

    # Prevent duplicate stars
    __table_args__ = (
        # UniqueConstraint('experiment_id', 'user_id', name='uq_experiment_user_star'),
    )


class ExperimentNote(Base):
    """Markdown notes attached to experiments.

    Users can document experiment insights, findings, and decisions.
    """

    __tablename__ = "experiment_notes"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)  # Markdown format

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    experiment = relationship("Experiment", back_populates="notes")
    user = relationship("User")


class Session(Base):
    """Chat session model."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    state = Column(String(50), nullable=False, default="initial", index=True)
    temp_data = Column(JSON, nullable=False, default={})

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    training_jobs = relationship("TrainingJob", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    """Chat message model."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="messages")


class TrainingJob(Base):
    """Training job model (also serves as Experiment)."""

    __tablename__ = "training_jobs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    experiment_name = Column(String(200), nullable=True)
    tags = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    mlflow_experiment_id = Column(String(100), nullable=True)  # MLflow experiment ID
    mlflow_run_id = Column(String(100), nullable=True)  # MLflow run ID for this training

    framework = Column(String(50), nullable=False, default="timm")
    model_name = Column(String(100), nullable=False)
    task_type = Column(String(50), nullable=False)
    num_classes = Column(Integer, nullable=True)

    # Dataset reference (new approach)
    dataset_id = Column(String(100), ForeignKey('datasets.id', ondelete='SET NULL'), nullable=True, index=True)
    dataset_snapshot_id = Column(String(100), ForeignKey('datasets.id', ondelete='SET NULL'), nullable=True, index=True)  # Immutable snapshot reference
    dataset_version = Column(Integer, nullable=True)  # Deprecated: kept for backward compatibility

    # Legacy dataset path (backward compatibility)
    dataset_path = Column(String(500), nullable=True)  # Made nullable for transition
    dataset_format = Column(String(50), nullable=False, default="imagefolder")
    output_dir = Column(String(500), nullable=False)

    epochs = Column(Integer, nullable=False)
    batch_size = Column(Integer, nullable=False)
    learning_rate = Column(Float, nullable=False)

    # Advanced configuration (JSON field for optimizer, scheduler, augmentation, etc.)
    advanced_config = Column(JSON, nullable=True)

    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    process_id = Column(Integer, nullable=True)

    # Temporal Workflow ID (Phase 12: Temporal Orchestration)
    workflow_id = Column(String(200), nullable=True, index=True)

    final_accuracy = Column(Float, nullable=True)
    best_checkpoint_path = Column(String(500), nullable=True)
    last_checkpoint_path = Column(String(500), nullable=True)

    # Primary metric configuration
    primary_metric = Column(String(100), nullable=True, default="loss")  # Metric name to optimize (e.g., 'accuracy', 'mAP50', 'f1_score')
    primary_metric_mode = Column(String(10), nullable=True, default="min")  # 'min' or 'max'

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    creator = relationship("User", back_populates="created_training_jobs", foreign_keys=[created_by])
    session = relationship("Session", back_populates="training_jobs")
    project = relationship("Project", back_populates="training_jobs")
    experiment = relationship("Experiment", back_populates="training_jobs")
    dataset = relationship("Dataset", back_populates="training_jobs", foreign_keys=[dataset_id])
    dataset_snapshot = relationship("Dataset", back_populates="snapshot_training_jobs", foreign_keys=[dataset_snapshot_id])
    metrics = relationship("TrainingMetric", back_populates="job", cascade="all, delete-orphan")
    logs = relationship("TrainingLog", back_populates="job", cascade="all, delete-orphan")
    validation_results = relationship("ValidationResult", back_populates="job", cascade="all, delete-orphan")
    test_runs = relationship("TestRun", back_populates="training_job", cascade="all, delete-orphan")
    inference_jobs = relationship("InferenceJob", back_populates="training_job", cascade="all, delete-orphan")


class TrainingMetric(Base):
    """Training metric model."""

    __tablename__ = "training_metrics"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("training_jobs.id"), nullable=False)

    epoch = Column(Integer, nullable=False)
    step = Column(Integer, nullable=True)

    loss = Column(Float, nullable=True)
    accuracy = Column(Float, nullable=True)
    learning_rate = Column(Float, nullable=True)

    extra_metrics = Column(JSON, nullable=True)
    checkpoint_path = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("TrainingJob", back_populates="metrics")


class TrainingLog(Base):
    """Training log model for capturing stdout/stderr."""

    __tablename__ = "training_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("training_jobs.id"), nullable=False)

    log_type = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("TrainingJob", back_populates="logs")


class ValidationResult(Base):
    """Task-agnostic validation result model.

    Stores validation metrics for any computer vision task (classification,
    detection, segmentation, pose estimation, etc.) using flexible JSON fields.
    """

    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("training_jobs.id"), nullable=False, index=True)
    epoch = Column(Integer, nullable=False, index=True)

    # Task identification
    task_type = Column(String(50), nullable=False, index=True)

    # Primary metric (task-specific)
    primary_metric_value = Column(Float, nullable=True)
    primary_metric_name = Column(String(100), nullable=True)
    overall_loss = Column(Float, nullable=True)

    # Task-specific metrics stored as JSON
    metrics = Column(JSON, nullable=True)  # Overall metrics dict
    per_class_metrics = Column(JSON, nullable=True)  # Per-class/category metrics

    # Visualization data (task-specific)
    confusion_matrix = Column(JSON, nullable=True)  # Classification
    pr_curves = Column(JSON, nullable=True)  # Detection, Segmentation
    class_names = Column(JSON, nullable=True)  # Class/category labels
    visualization_data = Column(JSON, nullable=True)  # Additional viz data

    # Sample images for UI display
    sample_correct_images = Column(JSON, nullable=True)
    sample_incorrect_images = Column(JSON, nullable=True)

    # Checkpoint path for this validation epoch
    checkpoint_path = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("TrainingJob", back_populates="validation_results")
    image_results = relationship("ValidationImageResult", back_populates="validation_result", cascade="all, delete-orphan")


class ValidationImageResult(Base):
    """Task-agnostic image-level validation result model.

    Stores per-image validation results with fields supporting all task types.
    Only relevant fields are populated based on task_type.
    """

    __tablename__ = "validation_image_results"

    id = Column(Integer, primary_key=True, index=True)
    validation_result_id = Column(Integer, ForeignKey("validation_results.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("training_jobs.id"), nullable=False, index=True)
    epoch = Column(Integer, nullable=False, index=True)

    # Image information
    image_path = Column(String(500), nullable=True)  # Made nullable - path may not be available during training
    image_name = Column(String(200), nullable=False, index=True)
    image_index = Column(Integer, nullable=True)

    # Classification fields
    true_label = Column(String(100), nullable=True)
    true_label_id = Column(Integer, nullable=True)
    predicted_label = Column(String(100), nullable=True)
    predicted_label_id = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    top5_predictions = Column(JSON, nullable=True)  # List of (label, confidence)

    # Object Detection fields
    true_boxes = Column(JSON, nullable=True)  # List of ground truth bounding boxes
    predicted_boxes = Column(JSON, nullable=True)  # List of predicted bounding boxes

    # Segmentation fields
    true_mask_path = Column(String(500), nullable=True)
    predicted_mask_path = Column(String(500), nullable=True)

    # Pose Estimation fields
    true_keypoints = Column(JSON, nullable=True)  # Ground truth keypoints
    predicted_keypoints = Column(JSON, nullable=True)  # Predicted keypoints

    # Common metrics
    is_correct = Column(Boolean, nullable=False, default=False, index=True)
    iou = Column(Float, nullable=True)  # IoU for detection/segmentation
    oks = Column(Float, nullable=True)  # Object Keypoint Similarity for pose

    # Extra data for task-specific needs
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    validation_result = relationship("ValidationResult", back_populates="image_results")


# ========== Test Run Models ==========

class TestRun(Base):
    """
    Test run on a labeled dataset after training.

    Similar to validation but runs on a separate test set for final evaluation.
    """

    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, index=True)
    training_job_id = Column(Integer, ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    checkpoint_path = Column(String(500), nullable=False)
    dataset_path = Column(String(500), nullable=False)
    dataset_split = Column(String(20), default="test")

    # Status
    status = Column(String(20), nullable=False, index=True)  # pending, running, completed, failed
    error_message = Column(Text, nullable=True)

    # Task info
    task_type = Column(String(50), nullable=False)
    primary_metric_name = Column(String(50), nullable=True)
    primary_metric_value = Column(Float, nullable=True)

    # Metrics (task-agnostic JSON)
    overall_loss = Column(Float, nullable=True)
    metrics = Column(JSON, nullable=True)
    per_class_metrics = Column(JSON, nullable=True)
    confusion_matrix = Column(JSON, nullable=True)

    # Metadata
    class_names = Column(JSON, nullable=True)
    total_images = Column(Integer, default=0)
    inference_time_ms = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    training_job = relationship("TrainingJob", back_populates="test_runs")
    image_results = relationship("TestImageResult", back_populates="test_run", cascade="all, delete-orphan")


class TestImageResult(Base):
    """
    Per-image test result with predictions and ground truth.

    Similar to ValidationImageResult but for test set evaluation.
    """

    __tablename__ = "test_image_results"

    id = Column(Integer, primary_key=True, index=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    training_job_id = Column(Integer, ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Image information
    image_path = Column(String(500), nullable=True)
    image_name = Column(String(200), nullable=False)
    image_index = Column(Integer, nullable=True)

    # Classification fields
    true_label = Column(String(100), nullable=True)
    true_label_id = Column(Integer, nullable=True, index=True)
    predicted_label = Column(String(100), nullable=True)
    predicted_label_id = Column(Integer, nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    top5_predictions = Column(JSON, nullable=True)

    # Detection fields
    true_boxes = Column(JSON, nullable=True)
    predicted_boxes = Column(JSON, nullable=True)

    # Segmentation fields
    true_mask_path = Column(String(500), nullable=True)
    predicted_mask_path = Column(String(500), nullable=True)

    # Pose fields
    true_keypoints = Column(JSON, nullable=True)
    predicted_keypoints = Column(JSON, nullable=True)

    # Metrics
    is_correct = Column(Boolean, nullable=False, default=False, index=True)
    iou = Column(Float, nullable=True)
    oks = Column(Float, nullable=True)

    # Performance
    inference_time_ms = Column(Float, nullable=True)
    preprocessing_time_ms = Column(Float, default=0.0)
    postprocessing_time_ms = Column(Float, default=0.0)

    # Extra data
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    test_run = relationship("TestRun", back_populates="image_results")
    job = relationship("TrainingJob", foreign_keys=[training_job_id])


# ========== Inference Models ==========

class InferenceJob(Base):
    """
    Inference job on unlabeled images (production use case).

    No ground truth, no metrics - only predictions and visualizations.
    """

    __tablename__ = "inference_jobs"

    id = Column(Integer, primary_key=True, index=True)
    training_job_id = Column(Integer, ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    checkpoint_path = Column(String(500), nullable=False)

    # Input
    inference_type = Column(String(20), nullable=False)  # single, batch, dataset
    input_data = Column(JSON, nullable=True)

    # Status
    status = Column(String(20), nullable=False, index=True)
    error_message = Column(Text, nullable=True)

    # Task info
    task_type = Column(String(50), nullable=False)

    # Performance metrics
    total_images = Column(Integer, default=0)
    total_inference_time_ms = Column(Float, nullable=True)
    avg_inference_time_ms = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    training_job = relationship("TrainingJob", back_populates="inference_jobs")
    results = relationship("InferenceResult", back_populates="inference_job", cascade="all, delete-orphan")


class InferenceResult(Base):
    """
    Per-image inference result (no ground truth).

    Used for production inference on unlabeled images.
    """

    __tablename__ = "inference_results"

    id = Column(Integer, primary_key=True, index=True)
    inference_job_id = Column(Integer, ForeignKey("inference_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    training_job_id = Column(Integer, ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Image information
    image_path = Column(String(500), nullable=False)
    image_name = Column(String(200), nullable=False)
    image_index = Column(Integer, nullable=True)

    # Classification predictions
    predicted_label = Column(String(100), nullable=True)
    predicted_label_id = Column(Integer, nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    top5_predictions = Column(JSON, nullable=True)

    # Raw predictions (task-agnostic)
    predictions = Column(JSON, nullable=True)  # Store all predictions from predict.py

    # Detection predictions (structured)
    predicted_boxes = Column(JSON, nullable=True)

    # Segmentation predictions
    predicted_mask_path = Column(String(500), nullable=True)

    # Pose predictions
    predicted_keypoints = Column(JSON, nullable=True)

    # Performance
    inference_time_ms = Column(Float, nullable=False)
    preprocessing_time_ms = Column(Float, default=0.0)
    postprocessing_time_ms = Column(Float, default=0.0)

    # Visualization
    visualization_path = Column(String(500), nullable=True)

    # Extra data
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    inference_job = relationship("InferenceJob", back_populates="results")
    job = relationship("TrainingJob", foreign_keys=[training_job_id])


# ========== Model Export & Deployment Models ==========

class ExportFormat(str, enum.Enum):
    """Supported export formats for model conversion."""
    ONNX = "onnx"
    TENSORRT = "tensorrt"
    COREML = "coreml"
    TFLITE = "tflite"
    TORCHSCRIPT = "torchscript"
    OPENVINO = "openvino"


class ExportJobStatus(str, enum.Enum):
    """Export job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentType(str, enum.Enum):
    """Deployment type for exported models."""
    DOWNLOAD = "download"  # Self-hosted download
    PLATFORM_ENDPOINT = "platform_endpoint"  # Triton Inference Server endpoint
    EDGE_PACKAGE = "edge_package"  # Mobile/embedded package (iOS, Android)
    CONTAINER = "container"  # Docker container with runtime


class DeploymentStatus(str, enum.Enum):
    """Deployment status."""
    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    FAILED = "failed"


class DeploymentEventType(str, enum.Enum):
    """Deployment history event types."""
    DEPLOYED = "deployed"
    SCALED = "scaled"
    DEACTIVATED = "deactivated"
    REACTIVATED = "reactivated"
    UPDATED = "updated"
    ERROR = "error"


class ExportJob(Base):
    """
    Model export job for converting trained checkpoints to production formats.

    Supports export to ONNX, TensorRT, CoreML, TFLite, TorchScript, OpenVINO
    with optimization options (quantization, pruning) and validation.
    """

    __tablename__ = "export_jobs"

    id = Column(Integer, primary_key=True, index=True)
    training_job_id = Column(Integer, ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Export configuration
    export_format = Column(SQLEnum(ExportFormat), nullable=False, index=True)
    checkpoint_path = Column(String(500), nullable=False)
    export_path = Column(String(500), nullable=True)  # Output path (populated after completion)

    # Version management (multiple exports from same training job)
    version = Column(Integer, nullable=False, default=1, index=True)
    is_default = Column(Boolean, nullable=False, default=False, index=True)  # Default export for this training job

    # Framework info (cached from training_job for quick access)
    framework = Column(String(50), nullable=False)
    task_type = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)

    # Export configuration (format-specific settings)
    export_config = Column(JSON, nullable=True)  # {opset_version, dynamic_axes, embed_preprocessing, etc.}
    optimization_config = Column(JSON, nullable=True)  # {quantization, pruning, etc.}
    validation_config = Column(JSON, nullable=True)  # {validate_outputs, tolerance, sample_inputs, etc.}

    # Status
    status = Column(SQLEnum(ExportJobStatus), nullable=False, default=ExportJobStatus.PENDING, index=True)
    error_message = Column(Text, nullable=True)
    process_id = Column(Integer, nullable=True)

    # Results (populated after completion)
    export_results = Column(JSON, nullable=True)  # {model_size_mb, inference_time_ms, validation_passed, etc.}
    file_size_mb = Column(Float, nullable=True)
    validation_passed = Column(Boolean, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    training_job = relationship("TrainingJob", backref="export_jobs", foreign_keys=[training_job_id])
    deployments = relationship("DeploymentTarget", back_populates="export_job", cascade="all, delete-orphan")


class DeploymentTarget(Base):
    """
    Deployment target for exported models.

    Manages deployment to different targets (download, platform endpoint, edge, container)
    with usage tracking and lifecycle management.
    """

    __tablename__ = "deployment_targets"

    id = Column(Integer, primary_key=True, index=True)
    export_job_id = Column(Integer, ForeignKey("export_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    training_job_id = Column(Integer, ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Deployment configuration
    deployment_type = Column(SQLEnum(DeploymentType), nullable=False, index=True)
    deployment_name = Column(String(200), nullable=False)  # User-friendly name
    deployment_config = Column(JSON, nullable=True)  # Type-specific config

    # Platform endpoint specific (Triton Inference Server)
    endpoint_url = Column(String(500), nullable=True)  # e.g., "http://triton:8000/v2/models/det-yolo11n/versions/1"
    api_key = Column(String(255), nullable=True)  # API key for authentication

    # Container specific
    container_image = Column(String(500), nullable=True)  # Docker image name:tag
    container_registry = Column(String(500), nullable=True)  # Registry URL

    # Edge package specific
    package_path = Column(String(500), nullable=True)  # Path to mobile/edge package
    runtime_wrapper_language = Column(String(50), nullable=True)  # python, cpp, swift, kotlin

    # Status
    status = Column(SQLEnum(DeploymentStatus), nullable=False, default=DeploymentStatus.PENDING, index=True)
    error_message = Column(Text, nullable=True)

    # Usage tracking
    request_count = Column(Integer, nullable=False, default=0)
    total_inference_time_ms = Column(Float, nullable=False, default=0.0)
    avg_latency_ms = Column(Float, nullable=True)
    last_request_at = Column(DateTime, nullable=True)

    # Resource usage (for platform endpoint)
    cpu_limit = Column(String(20), nullable=True)  # e.g., "2000m"
    memory_limit = Column(String(20), nullable=True)  # e.g., "4Gi"
    gpu_enabled = Column(Boolean, nullable=False, default=False)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deployed_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)

    # Relationships
    export_job = relationship("ExportJob", back_populates="deployments")
    training_job = relationship("TrainingJob", backref="deployments", foreign_keys=[training_job_id])
    history = relationship("DeploymentHistory", back_populates="deployment", cascade="all, delete-orphan")


class DeploymentHistory(Base):
    """
    Deployment event history for tracking lifecycle events.

    Records all deployment events: deployed, scaled, deactivated, reactivated, errors.
    """

    __tablename__ = "deployment_history"

    id = Column(Integer, primary_key=True, index=True)
    deployment_id = Column(Integer, ForeignKey("deployment_targets.id", ondelete="CASCADE"), nullable=False, index=True)

    # Event information
    event_type = Column(SQLEnum(DeploymentEventType), nullable=False, index=True)
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)  # Additional event-specific data

    # User tracking (nullable for system events)
    triggered_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    deployment = relationship("DeploymentTarget", back_populates="history")
    user = relationship("User")
