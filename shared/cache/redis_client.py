import json
import logging
from typing import Literal, TypedDict

import redis.asyncio as aioredis
from redis.asyncio import Redis

from shared.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None

NOT_FOUND_SENTINEL = "__NOT_FOUND__"


class AppCacheData(TypedDict):
    id: str
    status: str
    custom_index: str
    spa_fallback: bool


def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            encoding="utf-8",
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def get_app_cache(
    subdomain: str,
) -> AppCacheData | Literal["not_found"] | None:
    try:
        client = get_redis()
        raw = await client.get(f"app:{subdomain.lower()}")
        if raw is None:
            return None
        if raw == NOT_FOUND_SENTINEL:
            return "not_found"
        parsed = json.loads(raw)
        return AppCacheData(
            id=str(parsed["id"]),
            status=str(parsed["status"]),
            custom_index=str(parsed.get("custom_index", "index.html")),
            spa_fallback=bool(parsed.get("spa_fallback", False)),
        )
    except Exception as exc:
        logger.warning(f"Redis get_app_cache failed for subdomain {subdomain}: {exc}")
        return None


async def set_app_cache(
    subdomain: str,
    data: AppCacheData,
    ttl: int = 60,
) -> None:
    try:
        client = get_redis()
        payload = json.dumps(data)
        await client.set(f"app:{subdomain.lower()}", payload, ex=ttl)
    except Exception as exc:
        logger.warning(f"Redis set_app_cache failed for subdomain {subdomain}: {exc}")


async def set_app_not_found(
    subdomain: str,
    ttl: int = 60,
) -> None:
    try:
        client = get_redis()
        await client.set(f"app:{subdomain.lower()}", NOT_FOUND_SENTINEL, ex=ttl)
    except Exception as exc:
        logger.warning(f"Redis set_app_not_found failed for subdomain {subdomain}: {exc}")


async def invalidate_app_cache(subdomain: str) -> None:
    try:
        client = get_redis()
        await client.delete(f"app:{subdomain.lower()}")
    except Exception as exc:
        logger.warning(f"Redis invalidate_app_cache failed for subdomain {subdomain}: {exc}")


async def store_refresh_token(jti: str, user_id: str, ttl_seconds: int) -> None:
    try:
        client = get_redis()
        await client.set(f"refresh:{jti}", user_id, ex=ttl_seconds)
    except Exception as exc:
        logger.warning(f"Redis store_refresh_token failed for jti {jti}: {exc}")


async def verify_refresh_token_in_cache(jti: str) -> str | None:
    try:
        client = get_redis()
        user_id = await client.get(f"refresh:{jti}")
        return str(user_id) if user_id else None
    except Exception as exc:
        logger.warning(f"Redis verify_refresh_token_in_cache failed for jti {jti}: {exc}")
        return None


async def revoke_refresh_token(jti: str) -> None:
    try:
        client = get_redis()
        await client.delete(f"refresh:{jti}")
    except Exception as exc:
        logger.warning(f"Redis revoke_refresh_token failed for jti {jti}: {exc}")
