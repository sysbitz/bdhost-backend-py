from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.cache.redis_client import (
    AppCacheData,
    get_app_cache,
    set_app_cache,
    set_app_not_found,
)
from shared.config import get_settings
from shared.constants import RESERVED_SUBDOMAINS, SUBDOMAIN_REGEX
from shared.db.models import App


def extract_subdomain(host: str | None) -> str | None:
    """Extracts and validates a single-level platform subdomain from the Host header.

    Security & Validation:
    - Normalizes hostname (strips port, trims, lowercases).
    - Rejects exact base domain (e.g. bdappshub.com) or localhost.
    - Strictly matches base domain suffix (e.g. .bdappshub.com, or .localhost in dev).
    - Enforces single-level subdomain (rejects multi-level names like a.b.bdappshub.com).
    - Validates against SUBDOMAIN_REGEX (RFC 1123 compliant, 3-63 chars).
    - Rejects reserved system names (api, auth, admin, etc.).
    """
    if not host:
        return None

    # Strip port if present
    host_without_port = host.split(":")[0].strip().lower()
    if not host_without_port:
        return None

    settings = get_settings()
    base_domain = settings.base_domain.lower().strip(".")

    # Direct match with base_domain or localhost is not a tenant
    if host_without_port in (base_domain, "localhost", "127.0.0.1"):
        return None

    # Check suffix
    expected_suffix = f".{base_domain}"
    if host_without_port.endswith(expected_suffix):
        subdomain = host_without_port[: -len(expected_suffix)]
    elif settings.is_development and host_without_port.endswith(".localhost"):
        subdomain = host_without_port[: -len(".localhost")]
    else:
        # Arbitrary foreign host (e.g. evil.com)
        return None

    # Enforce single-level subdomain (no nested dots)
    if not subdomain or "." in subdomain:
        return None

    # Enforce regex validation
    if not SUBDOMAIN_REGEX.match(subdomain):
        return None

    # Reject reserved platform subdomains
    if subdomain in RESERVED_SUBDOMAINS:
        return None

    return subdomain


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
