import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from api.schemas import AppCreate, AppOut, AppUpdate
from api.services.app_service import (
    create_app,
    delete_app,
    get_app,
    list_apps,
    to_app_out,
    update_app,
)
from shared.db.models import User

router = APIRouter(prefix="/apps", tags=["apps"])


@router.post("", response_model=AppOut, status_code=status.HTTP_201_CREATED)
async def create_new_app(
    data: AppCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppOut:
    return await create_app(db=db, user=current_user, data=data)


@router.get("", response_model=list[AppOut])
async def list_user_apps(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AppOut]:
    return await list_apps(db=db, user=current_user)


@router.get("/{app_id}", response_model=AppOut)
async def get_single_app(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppOut:
    app = await get_app(db=db, app_id=app_id, user=current_user)
    return to_app_out(app)


@router.patch("/{app_id}", response_model=AppOut)
async def update_single_app(
    app_id: uuid.UUID,
    data: AppUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppOut:
    return await update_app(db=db, app_id=app_id, user=current_user, data=data)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_single_app(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await delete_app(db=db, app_id=app_id, user=current_user)
