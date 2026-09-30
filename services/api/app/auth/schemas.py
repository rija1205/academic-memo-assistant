from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserResponse
    csrf_token: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=12, max_length=128)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)


class MessageResponse(BaseModel):
    message: str


class SessionResponse(BaseModel):
    id: UUID
    current: bool
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    user_agent: str | None


class CsrfResponse(BaseModel):
    csrf_token: str


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str | None = None


class GoogleStatusResponse(BaseModel):
    enabled: bool


class GoogleStartResponse(BaseModel):
    authorization_url: str
