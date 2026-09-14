import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import App, Plan, User
from shared.enums import AppStatus, UserRole


async def get_user_effective_plan(db: AsyncSession, user_id: uuid.UUID) -> Plan:
    """Returns the user's active plan, defaulting to Free plan if none assigned."""
    result = await db.execute(select(Plan).order_by(Plan.price.asc()).limit(1))
    default_plan = result.scalar_one_or_none()
    if not default_plan:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No plans configured in system",
        )
    return default_plan


async def check_app_limit(db: AsyncSession, user: User, plan_id: uuid.UUID | None = None) -> Plan:
    """Verifies that user hasn't exceeded their maximum allowed app limit."""
    if user.role == UserRole.ADMIN:
        # Admin has no restriction, fetch plan or default
        if plan_id:
            plan_res = await db.execute(select(Plan).where(Plan.id == plan_id))
            plan = plan_res.scalar_one_or_none()
            if plan:
                return plan
        return await get_user_effective_plan(db, user.id)

    # Fetch requested or default plan
    if plan_id:
        plan_res = await db.execute(select(Plan).where(Plan.id == plan_id))
        plan = plan_res.scalar_one_or_none()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Selected plan not found",
            )
    else:
        plan = await get_user_effective_plan(db, user.id)

    # Count active apps
    apps_count_res = await db.execute(
        select(func.count(App.id)).where(
            App.owner_id == user.id,
            App.status != AppStatus.DELETED,
        )
    )
    current_apps_count = apps_count_res.scalar_one() or 0

    if current_apps_count >= plan.app_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"App creation limit reached ({plan.app_limit} apps allowed on '{plan.name}' plan). Please upgrade your plan.",
        )

    return plan


async def verify_storage_quota(
    db: AsyncSession,
    app: App,
    additional_bytes: int,
) -> None:
    """Checks if adding `additional_bytes` exceeds the app's plan storage quota."""
    plan_res = await db.execute(select(Plan).where(Plan.id == app.plan_id))
    plan = plan_res.scalar_one_or_none()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Associated plan not found for app",
        )

    max_bytes = plan.storage_limit_mb * 1024 * 1024
    if app.storage_bytes_used + additional_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Storage limit exceeded for app. Current: {app.storage_bytes_used / (1024 * 1024):.2f}MB, "
                f"New: {additional_bytes / (1024 * 1024):.2f}MB, Max allowed: {plan.storage_limit_mb}MB"
            ),
        )
