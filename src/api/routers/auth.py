import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.cache.redis_client import (
    revoke_refresh_token,
    store_refresh_token,
    verify_refresh_token_in_cache,
)
from shared.config import get_settings
from shared.db.models import RefreshToken, User
from shared.enums import UserRole
from src.api.core.rate_limit import auth_limiter
from src.api.core.security import (
    create_access_token,
    generate_refresh_token,
    get_password_hash,
    verify_password,
)
from src.api.deps import get_current_user, get_db
from src.api.schemas import (
    AdminSetupRequest,
    AdminSetupResponse,
    AdminSetupStatus,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/setup-status", response_model=AdminSetupStatus)
async def get_admin_setup_status(
    db: AsyncSession = Depends(get_db),
) -> AdminSetupStatus:
    """Checks whether the initial admin setup has been completed."""
    result = await db.execute(select(User.id).where(User.role == UserRole.ADMIN).limit(1))
    admin_exists = result.scalar_one_or_none() is not None

    if admin_exists:
        return AdminSetupStatus(
            admin_setup_required=False,
            message="Admin account has already been initialized. Setup is locked.",
        )
    return AdminSetupStatus(
        admin_setup_required=True,
        message="No administrator exists. Initial setup required.",
    )


@router.post(
    "/setup-admin",
    response_model=AdminSetupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_limiter)],
)
async def setup_initial_admin(
    data: AdminSetupRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AdminSetupResponse:
    """One-time initial admin setup endpoint.

    Allows creating the administrator account on first boot.
    Once an admin account exists, this endpoint is permanently locked and returns 403 Forbidden.
    """
    settings = get_settings()

    # 1. Verify that NO admin account exists
    admin_check = await db.execute(select(User.id).where(User.role == UserRole.ADMIN).limit(1))
    if admin_check.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account setup has already been completed. This endpoint is permanently disabled.",
        )

    normalized_email = data.email.strip().lower()

    # 2. Verify email uniqueness
    existing_user = await db.execute(select(User).where(User.email == normalized_email))
    if existing_user.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 3. Create the administrator account
    admin_user = User(
        email=normalized_email,
        password_hash=get_password_hash(data.password),
        full_name=data.full_name.strip() or "System Administrator",
        role=UserRole.ADMIN,
    )
    db.add(admin_user)
    await db.commit()
    await db.refresh(admin_user)

    # 4. Generate access token and refresh token session
    access_token = create_access_token(subject=str(admin_user.id), role=str(admin_user.role))
    jti = generate_refresh_token()
    ttl_seconds = settings.refresh_token_expire_days * 86400
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    db_token = RefreshToken(
        user_id=admin_user.id,
        jti=jti,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(db_token)
    await db.commit()

    await store_refresh_token(jti=jti, user_id=str(admin_user.id), ttl_seconds=ttl_seconds)
    _set_refresh_cookie(response, jti)

    return AdminSetupResponse(
        success=True,
        message="Admin account created successfully. Initial setup is now locked.",
        user=UserOut.model_validate(admin_user),
        access_token=access_token,
        token_type="bearer",
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=not settings.is_development,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
        path="/auth",
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_limiter)],
)
async def register(
    data: UserRegister,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    normalized_email = data.email.strip().lower()

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == normalized_email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # First user can be promoted or default to USER role
    user = User(
        email=normalized_email,
        password_hash=get_password_hash(data.password),
        full_name=data.full_name.strip(),
        role=UserRole.USER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(auth_limiter)],
)
async def login(
    data: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    normalized_email = data.email.strip().lower()

    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Generate access token
    access_token = create_access_token(subject=str(user.id), role=str(user.role))

    # Generate refresh token
    jti = generate_refresh_token()
    ttl_seconds = settings.refresh_token_expire_days * 86400
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    # Persist in DB
    db_token = RefreshToken(
        user_id=user.id,
        jti=jti,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(db_token)
    await db.commit()

    # Mirror in Redis for O(1) revocation checks
    await store_refresh_token(jti=jti, user_id=str(user.id), ttl_seconds=ttl_seconds)

    # Set httpOnly cookie
    _set_refresh_cookie(response, jti)

    return TokenResponse(access_token=access_token, token_type="bearer")


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie missing",
        )

    # Fast path: check Redis
    cached_user_id = await verify_refresh_token_in_cache(refresh_token)
    token_record: RefreshToken | None = None

    if cached_user_id:
        user_id_str = cached_user_id
    else:
        # Fallback to database check
        token_res = await db.execute(
            select(RefreshToken).where(
                RefreshToken.jti == refresh_token,
                RefreshToken.revoked.is_(False),
            )
        )
        token_record = token_res.scalar_one_or_none()
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
        user_id_str = str(token_record.user_id)

    # Fetch User
    user_uuid = uuid.UUID(user_id_str)
    user_res = await db.execute(select(User).where(User.id == user_uuid))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Rotate Refresh Token: Revoke old
    await revoke_refresh_token(refresh_token)
    await db.execute(
        update(RefreshToken).where(RefreshToken.jti == refresh_token).values(revoked=True)
    )

    # Create new refresh token
    new_jti = generate_refresh_token()
    ttl_seconds = settings.refresh_token_expire_days * 86400
    new_expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    db.add(
        RefreshToken(
            user_id=user.id,
            jti=new_jti,
            expires_at=new_expires_at,
            revoked=False,
        )
    )
    await db.commit()

    await store_refresh_token(jti=new_jti, user_id=str(user.id), ttl_seconds=ttl_seconds)

    # Generate new access token
    new_access_token = create_access_token(subject=str(user.id), role=str(user.role))
    _set_refresh_cookie(response, new_jti)

    return TokenResponse(access_token=new_access_token, token_type="bearer")


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if refresh_token:
        # Revoke in Redis
        await revoke_refresh_token(refresh_token)
        # Revoke in DB
        await db.execute(
            update(RefreshToken).where(RefreshToken.jti == refresh_token).values(revoked=True)
        )
        await db.commit()

    response.delete_cookie(key="refresh_token", path="/auth")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
