from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import App, User
from shared.enums import AppStatus
from src.api.deps import get_current_user, get_db
from src.api.schemas import UserOut

router = APIRouter(prefix="/account", tags=["account"])


class AccountStatsOut(BaseModel):
    user: UserOut
    total_apps: int
    total_storage_bytes: int


class AccountUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)


@router.get("", response_model=AccountStatsOut)
async def get_account_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccountStatsOut:
    # Query app counts and storage sum
    stats_query = select(
        func.count(App.id).label("total_apps"),
        func.coalesce(func.sum(App.storage_bytes_used), 0).label("total_storage"),
    ).where(
        App.owner_id == current_user.id,
        App.status != AppStatus.DELETED,
    )
    result = await db.execute(stats_query)
    row = result.one()

    return AccountStatsOut(
        user=UserOut.model_validate(current_user),
        total_apps=row.total_apps,
        total_storage_bytes=row.total_storage,
    )


@router.patch("", response_model=UserOut)
async def update_account_details(
    data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserOut:
    if data.full_name is not None:
        current_user.full_name = data.full_name.strip()
        await db.commit()
        await db.refresh(current_user)

    return UserOut.model_validate(current_user)
