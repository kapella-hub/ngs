"""Authentication schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import UserRole


class UserBase(BaseModel):
    """Base user schema."""
    username: str = Field(..., min_length=3, max_length=255)
    email: EmailStr
    display_name: Optional[str] = None


class UserCreate(UserBase):
    """Create user request."""
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.VIEWER


class UserUpdate(BaseModel):
    """Update user request."""
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    """User response schema."""
    id: UUID
    role: UserRole
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """Token payload data."""
    sub: str
    role: UserRole
    exp: datetime


class LoginRequest(BaseModel):
    """Login request."""
    username: str
    password: str


class PasswordChange(BaseModel):
    """Password change request."""
    current_password: str
    new_password: str = Field(..., min_length=8)
