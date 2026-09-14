from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.cache.redis_client import (
    AppCacheData,
    get_app_cache,
    set_app_cache,
    set_app_not_found,
)
from shared.config import get_settings
from shared.db.models import App


def extract_subdomain(host: str | None) -> str | None:
    if not host:
        return None

    # Strip port if present
    host_without_port = host.split(":")[0].strip().lower()

    # Split by dot
    parts = host_without_port.split(".")

    # If format is "sub.bdappshub.com" or "sub.localhost"
    if len(parts) >= 2:
        settings = get_settings()
        base_domain = settings.base_domain.lower()

        # If it's directly base_domain without subdomain
        if host_without_port == base_domain:
            return None

        # Return first segment
        return parts[0]

    return None


async def resolve_app(
    subdomain: str,
    db: AsyncSession,
) -> AppCacheData | None:
    # 1. Check Redis cache
    cached = await get_app_cache(subdomain)
    if cached == "not_found":
        return None
    if cached is not None:
        return cached

    # 2. Cache miss: query Postgres
    # (Only select the 4 columns specified in spec section 6: id, status, custom_index, spa_fallback)
    query = select(
        App.id,
        App.status,
        App.custom_index,
        App.spa_fallback,
    ).where(App.subdomain == subdomain.lower())

    result = await db.execute(query)
    row = result.first()

    if not row:
        # Negative cache for 60 seconds
        await set_app_not_found(subdomain, ttl=60)
        return None

    # 3. Populate Redis cache
    app_data: AppCacheData = {
        "id": str(row.id),
        "status": str(row.status),
        "custom_index": str(row.custom_index or "index.html"),
        "spa_fallback": bool(row.spa_fallback),
    }
    await set_app_cache(subdomain, app_data, ttl=60)

    return app_data
