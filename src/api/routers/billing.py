from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Plan, User
from src.api.deps import get_current_user, get_db
from src.api.schemas import PlanOut
from src.api.services.quota_service import get_user_effective_plan

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[PlanOut])
async def list_available_plans(
    db: AsyncSession = Depends(get_db),
) -> list[PlanOut]:
    result = await db.execute(select(Plan).order_by(Plan.price.asc()))
    plans = result.scalars().all()
    return [PlanOut.model_validate(p) for p in plans]


@router.get("/subscription", response_model=PlanOut)
async def get_current_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanOut:
    plan = await get_user_effective_plan(db, current_user.id)
    return PlanOut.model_validate(plan)
