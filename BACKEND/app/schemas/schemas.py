"""
Pydantic schemas for API requests and responses.
"""
from typing import Optional, List, Any, Dict
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# ============================================
# Standardized API Response Schema
# ============================================

class APIResponse(BaseModel):
    """Standard API response format for all endpoints."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
    errors: List[str] = []
    meta: Dict[str, Any] = {}


# ============================================
# User Schemas
# ============================================

class UserBase(BaseModel):
    """Base user schema with common fields."""
    email: EmailStr = Field(..., description="User's email address")
    username: Optional[str] = Field(None, description="User's username")


class UserCreate(UserBase):
    """Schema for user registration."""
    password: str = Field(..., min_length=8, description="User's password (min 8 characters)")
    confirm_password: str = Field(..., description="Password confirmation")


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")


class UserResponse(UserBase):
    """Schema for user data in responses."""
    id: int
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Schema for updating user profile."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None


# ============================================
# Token Schemas
# ============================================

class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for JWT token payload."""
    sub: str  # Subject (usually email)
    type: str  # Token type (access/refresh)
    exp: datetime  # Expiration time
    iat: datetime  # Issued at time
    jti: Optional[str] = None  # JWT ID for revocation


# ============================================
# Role Schemas
# ============================================

class RoleBase(BaseModel):
    """Base role schema."""
    name: str = Field(..., description="Role name")
    description: Optional[str] = Field(None, description="Role description")


class RoleCreate(RoleBase):
    """Schema for creating a role."""
    pass


class RoleResponse(RoleBase):
    """Schema for role data in responses."""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# Audit Log Schemas
# ============================================

class AuditLogBase(BaseModel):
    """Base audit log schema."""
    action: str = Field(..., description="Action performed")
    resource: str = Field(..., description="Resource type")
    resource_id: Optional[int] = Field(None, description="Resource ID")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class AuditLogResponse(AuditLogBase):
    """Schema for audit log in responses."""
    id: int
    user_id: int
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


# ============================================
# Error Schemas
# ============================================

class ErrorDetail(BaseModel):
    """Schema for error details."""
    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """Schema for error responses."""
    success: bool = False
    data: Optional[Any] = None
    message: str
    errors: List[str] = []
    meta: Dict[str, Any] = {}
