from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import App, User
from shared.enums import AppStatus
from src.api.deps import get_current_admin, get_db
from src.api.schemas import AdminOverviewOut, AppOut, UserOut
from src.api.services.app_service import to_app_out

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewOut)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> AdminOverviewOut:
    """Returns platform overview statistics for the admin dashboard."""
    # Count total users
    user_count_res = await db.execute(select(func.count(User.id)))
    total_users = user_count_res.scalar() or 0

    # Count total apps (non-deleted)
    app_count_res = await db.execute(
        select(func.count(App.id)).where(App.status != AppStatus.DELETED)
    )
    total_apps = app_count_res.scalar() or 0

    # Count active apps
    active_count_res = await db.execute(
        select(func.count(App.id)).where(App.status == AppStatus.ACTIVE)
    )
    active_apps = active_count_res.scalar() or 0

    # Total storage used across non-deleted apps
    storage_res = await db.execute(
        select(func.sum(App.storage_bytes_used)).where(App.status != AppStatus.DELETED)
    )
    total_storage = storage_res.scalar() or 0

    return AdminOverviewOut(
        total_users=total_users,
        total_apps=total_apps,
        active_apps=active_apps,
        total_storage_bytes=int(total_storage),
    )


@router.get("/users", response_model=list[UserOut])
async def list_all_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> list[UserOut]:
    """Lists all registered users on the platform."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [UserOut.model_validate(u) for u in users]


@router.get("/apps", response_model=list[AppOut])
async def list_all_apps(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> list[AppOut]:
    """Lists all applications on the platform across all users."""
    result = await db.execute(
        select(App).where(App.status != AppStatus.DELETED).order_by(App.created_at.desc())
    )
    apps = result.scalars().all()
    return [to_app_out(app) for app in apps]
