import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from shared.db.base import async_session_factory
from shared.db.models import App
from shared.enums import AppStatus
from shared.storage.r2_client import get_r2_client

logger = logging.getLogger(__name__)


async def recalc_quota(ctx: dict[str, Any], app_id: str | None = None) -> dict[str, Any]:
    """Reconciles storage_bytes_used in PostgreSQL against actual R2 bucket usage."""
    r2 = get_r2_client()
    session_maker = async_session_factory()

    async with session_maker() as session:
        if app_id:
            app_uuid = uuid.UUID(app_id) if isinstance(app_id, str) else app_id
            query = select(App).where(App.id == app_uuid)
            result = await session.execute(query)
            apps = [result.scalar_one_or_none()]
        else:
            query = select(App).where(App.status != AppStatus.DELETED)
            result = await session.execute(query)
            apps = list(result.scalars().all())

        updated_count = 0
        total_recalculated_bytes = 0

        for app in apps:
            if not app:
                continue
            prefix = f"apps/{app.id}/"
            actual_bytes = await r2.calculate_prefix_size(prefix)

            if app.storage_bytes_used != actual_bytes:
                logger.info(
                    f"Recalculating quota for app {app.subdomain} ({app.id}): "
                    f"was {app.storage_bytes_used} bytes, now {actual_bytes} bytes"
                )
                await session.execute(
                    update(App).where(App.id == app.id).values(storage_bytes_used=actual_bytes)
                )
                updated_count += 1

            total_recalculated_bytes += actual_bytes

        await session.commit()

        return {
            "apps_scanned": len(apps),
            "apps_updated": updated_count,
            "total_bytes": total_recalculated_bytes,
        }


async def send_email(ctx: dict[str, Any], to: str, subject: str, body: str) -> bool:
    """Stubbed async email sender for welcome emails, notifications, and alerts."""
    logger.info(f"[EMAIL MOCK] To: {to} | Subject: {subject} | Content length: {len(body)} chars")
    return True
