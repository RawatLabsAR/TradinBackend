"""Auth and admin user management schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    role: Literal["admin", "user"]
    telegram_number: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    telegram_number: Optional[str] = Field(default=None, max_length=32)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, hyphens, and underscores")
        return v


class UserUpdate(BaseModel):
    telegram_number: Optional[str] = Field(default=None, max_length=32)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class UserListResponse(BaseModel):
    users: list[UserOut]
    total: int


class ActivityLogOut(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str]
    action: str
    action_label: Optional[str] = None
    resource_type: Optional[str]
    resource_id: Optional[str]
    detail: Optional[str]
    metadata: Optional[dict[str, Any]] = Field(default=None, validation_alias="meta")
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ActivityListResponse(BaseModel):
    items: list[ActivityLogOut]
    total: int
    page: int
    page_size: int
    pages: int


class ActivityFilterOptions(BaseModel):
    actions: list[str]
    action_labels: dict[str, str]
    resource_types: list[str]
    users: list[dict[str, Any]]
    action_prefixes: list[str]
