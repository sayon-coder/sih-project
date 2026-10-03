"""
Authentication and user management services.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, Request
from app.models import User, Role, UserRole, RoleName
from app.schemas import UserCreate
from app.utils import hash_password, verify_password, create_access_token, create_refresh_token
from app.services.audit_service import AuditService


class AuthService:
    """Service for authentication operations."""

    @staticmethod
    def register_user(
        db: Session,
        user_data: UserCreate,
        request: Optional[Request] = None
    ) -> User:
        """
        Register a new user.

        Args:
            db: Database session
            user_data: User registration data
            request: FastAPI request for audit logging

        Returns:
            Created User instance

        Raises:
            HTTPException: If email already registered or passwords don't match
        """
        # Check if passwords match
        if user_data.password != user_data.confirm_password:
            raise HTTPException(
                status_code=400,
                detail="Passwords do not match"
            )

        # Check if email already exists
        existing_user = db.query(User).filter(
            User.email == user_data.email
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

        # Create user
        user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password)
        )

        try:
            db.add(user)
            db.commit()
            db.refresh(user)

            # Assign default VIEWER role
            AuthService.assign_role(db, user.id, RoleName.VIEWER)

            # Audit log
            AuditService.log_action(
                db=db,
                user_id=user.id,
                action="register",
                resource="user",
                resource_id=user.id,
                details={"email": user.email, "username": user.username},
                request=request
            )

            return user

        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

    @staticmethod
    def authenticate_user(
        db: Session,
        email: str,
        password: str,
        request: Optional[Request] = None
    ) -> dict:
        """
        Authenticate user and return tokens.

        Args:
            db: Database session
            email: User email
            password: User password
            request: FastAPI request for audit logging

        Returns:
            Dict with access_token and token_type

        Raises:
            HTTPException: If credentials are invalid
        """
        # Find user
        user = db.query(User).filter(User.email == email).first()

        if not user or not verify_password(password, user.password_hash):
            # Audit failed login attempt
            AuditService.log_action(
                db=db,
                user_id=user.id if user else None,
                action="login_failed",
                resource="user",
                details={"email": email, "reason": "invalid_credentials"},
                request=request
            )
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Account is deactivated"
            )

        # Create tokens
        access_token = create_access_token({"sub": str(user.id)})

        # Audit successful login
        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="login",
            resource="user",
            resource_id=user.id,
            request=request
        )

        return {
            "access_token": access_token,
            "token_type": "bearer"
        }

    @staticmethod
    def assign_role(
        db: Session,
        user_id: int,
        role_name: RoleName
    ) -> UserRole:
        """
        Assign a role to a user.

        Args:
            db: Database session
            user_id: User ID
            role_name: Role name enum

        Returns:
            Created UserRole instance

        Raises:
            HTTPException: If user or role not found
        """
        # Check user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get role
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # Check if role already assigned
        existing = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id
        ).first()

        if existing:
            return existing

        # Assign role
        user_role = UserRole(user_id=user_id, role_id=role.id)
        db.add(user_role)
        db.commit()
        db.refresh(user_role)

        return user_role

    @staticmethod
    def get_user_roles(db: Session, user_id: int) -> List[RoleName]:
        """
        Get all roles for a user.

        Args:
            db: Database session
            user_id: User ID

        Returns:
            List of RoleName enums
        """
        user_roles = db.query(UserRole).filter(
            UserRole.user_id == user_id
        ).all()

        return [ur.role.name for ur in user_roles]

    @staticmethod
    def has_role(db: Session, user_id: int, role_name: RoleName) -> bool:
        """
        Check if user has a specific role.

        Args:
            db: Database session
            user_id: User ID
            role_name: Role name to check

        Returns:
            True if user has role, False otherwise
        """
        user_roles = AuthService.get_user_roles(db, user_id)
        return role_name in user_roles
