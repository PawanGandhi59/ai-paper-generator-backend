import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _validate_person_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Name cannot be empty or blank")
    if not re.search(r'[a-zA-Z\u00C0-\u024F\u1E00-\u1EFF]', v):
        raise ValueError("Name must contain at least one letter and cannot consist only of numbers, dots, or symbols")
    return v


class UserRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_person_name(v)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return v.strip()


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return v.strip()


class GoogleLogin(BaseModel):
    id_token: str = Field(..., min_length=1)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    is_active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return v.strip()


class ForgotPasswordResponse(BaseModel):
    message: str


class VerifyResetOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., pattern=r"^\d{6}$")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return v.strip()


class VerifyResetOTPResponse(BaseModel):
    message: str
    reset_token: str


class ResetPasswordRequest(BaseModel):
    reset_token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=72)


class ResetPasswordResponse(BaseModel):
    message: str
