import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.cache.redis_client import invalidate_app_cache
from shared.config import get_settings
from shared.constants import RESERVED_SUBDOMAINS, SUBDOMAIN_REGEX
from shared.db.models import App, User
from shared.enums import AppStatus, UserRole
from shared.storage.r2_client import get_r2_client
from shared.utils.path import sanitize_relative_path
from src.api.schemas import AppCreate, AppOut, AppUpdate
from src.api.services.quota_service import check_app_limit


def validate_subdomain(subdomain: str) -> str:
    cleaned = subdomain.strip().lower()
    if len(cleaned) < 3 or len(cleaned) > 63:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subdomain must be between 3 and 63 characters.",
        )
    if not SUBDOMAIN_REGEX.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subdomain may only contain lowercase letters, numbers, and non-consecutive internal hyphens.",
        )
    if cleaned in RESERVED_SUBDOMAINS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Subdomain '{cleaned}' is reserved and cannot be registered.",
        )
    return cleaned


def to_app_out(app: App) -> AppOut:
    settings = get_settings()
    protocol = "http" if settings.is_development else "https"
    live_url = f"{protocol}://{app.subdomain}.{settings.base_domain}"
    return AppOut(
        id=app.id,
        subdomain=app.subdomain,
        status=app.status,
        plan_id=app.plan_id,
        storage_bytes_used=app.storage_bytes_used,
        custom_index=app.custom_index,
        spa_fallback=app.spa_fallback,
        created_at=app.created_at,
        updated_at=app.updated_at,
        live_url=live_url,
    )


async def create_app(db: AsyncSession, user: User, data: AppCreate) -> AppOut:
    subdomain = validate_subdomain(data.subdomain)

    # Check uniqueness
    existing = await db.execute(select(App).where(App.subdomain == subdomain))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Subdomain '{subdomain}' is already taken.",
        )

    # Check user app limits and get plan
    plan = await check_app_limit(db, user, data.plan_id)

    app = App(
        owner_id=user.id,
        subdomain=subdomain,
        plan_id=plan.id,
        status=AppStatus.ACTIVE,
        storage_bytes_used=0,
        custom_index="index.html",
        spa_fallback=False,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    # Invalidate negative cache in case subdomain was previously looked up
    await invalidate_app_cache(subdomain)

    return to_app_out(app)


async def list_apps(db: AsyncSession, user: User) -> list[AppOut]:
    query = select(App).where(App.status != AppStatus.DELETED)
    if user.role != UserRole.ADMIN:
        query = query.where(App.owner_id == user.id)
    query = query.order_by(App.created_at.desc())

    result = await db.execute(query)
    apps = result.scalars().all()
    return [to_app_out(app) for app in apps]


async def get_app(db: AsyncSession, app_id: uuid.UUID, user: User) -> App:
    query = select(App).where(App.id == app_id, App.status != AppStatus.DELETED)
    if user.role != UserRole.ADMIN:
        query = query.where(App.owner_id == user.id)

    result = await db.execute(query)
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found",
        )
    return app


async def update_app(db: AsyncSession, app_id: uuid.UUID, user: User, data: AppUpdate) -> AppOut:
    app = await get_app(db, app_id, user)

    if data.custom_index is not None:
        try:
            app.custom_index = sanitize_relative_path(data.custom_index)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid custom_index: {e}",
            )
    if data.spa_fallback is not None:
        app.spa_fallback = data.spa_fallback
    if data.status is not None:
        if user.role != UserRole.ADMIN and data.status not in (
            AppStatus.ACTIVE,
            AppStatus.SUSPENDED,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can set this status.",
            )
        app.status = data.status

    await db.commit()
    await db.refresh(app)

    # Invalidate runtime cache so changes take effect immediately
    await invalidate_app_cache(app.subdomain)

    return to_app_out(app)


async def delete_app(db: AsyncSession, app_id: uuid.UUID, user: User) -> bool:
    app = await get_app(db, app_id, user)

    # Clean up R2 storage
    r2 = get_r2_client()
    await r2.delete_objects_by_prefix(f"apps/{app.id}/")

    # Mark as deleted (or remove)
    app.status = AppStatus.DELETED
    app.storage_bytes_used = 0
    await db.commit()

    # Invalidate runtime cache
    await invalidate_app_cache(app.subdomain)

    return True
