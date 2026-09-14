import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from shared.enums import AppStatus, UserRole


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    created_at: datetime


class AdminSetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = "System Administrator"


class AdminSetupResponse(BaseModel):
    success: bool
    message: str
    user: UserOut
    access_token: str
    token_type: str = "bearer"


class AdminSetupStatus(BaseModel):
    admin_setup_required: bool
    message: str


class AdminOverviewOut(BaseModel):
    total_users: int
    total_apps: int
    active_apps: int
    total_storage_bytes: int


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    app_limit: int
    storage_limit_mb: int
    price: Decimal
    features: dict[str, Any]


class AppCreate(BaseModel):
    subdomain: str = Field(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$",
        description="Subdomain slug, 3-63 chars, lowercase alphanumeric with internal hyphens",
    )
    plan_id: uuid.UUID | None = None


class AppUpdate(BaseModel):
    custom_index: str | None = Field(default=None, max_length=255)
    spa_fallback: bool | None = None
    status: AppStatus | None = None


class AppOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subdomain: str
    status: AppStatus
    plan_id: uuid.UUID
    storage_bytes_used: int
    custom_index: str
    spa_fallback: bool
    created_at: datetime
    updated_at: datetime
    live_url: str


class FileItemOut(BaseModel):
    key: str
    size: int
    last_modified: datetime | None = None
    etag: str = ""


class FileListResponse(BaseModel):
    app_id: uuid.UUID
    storage_bytes_used: int
    files: list[FileItemOut]


class DeployResponse(BaseModel):
    success: bool
    message: str
    deployed_files: int
    total_bytes_written: int
    storage_bytes_used: int
