import logging
from typing import Any, Callable

from fastapi import Request, Response
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from shared.cache.redis_client import get_redis

logger = logging.getLogger(__name__)


async def init_rate_limiter() -> None:
    try:
        redis_client = get_redis()
        # Ping to check if Redis is responsive
        await redis_client.ping()
        await FastAPILimiter.init(redis_client)
        logger.info("fastapi-limiter initialized with Redis.")
    except Exception as exc:
        logger.warning(
            f"Failed to initialize fastapi-limiter with Redis (rate limiting disabled): {exc}"
        )


async def auth_rate_limit_identifier(request: Request) -> str:
    """Combines client IP and submitted email for rate limiting."""
    forwarded = request.headers.get("X-Forwarded-For")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else request.client.host
        if request.client
        else "unknown"
    )
    return f"auth:{ip}"


class SafeRateLimiter:
    """Rate limiter that gracefully allows requests if FastAPILimiter / Redis is not initialized."""

    def __init__(
        self,
        times: int = 5,
        seconds: int = 300,
        identifier: Callable[[Request], Any] | None = None,
    ) -> None:
        self.times = times
        self.seconds = seconds
        self.identifier = identifier
        self._limiter = RateLimiter(times=times, seconds=seconds, identifier=identifier)

    async def __call__(self, request: Request, response: Response) -> None:
        if not FastAPILimiter.redis:
            # If Redis or FastAPILimiter is not initialized, allow request gracefully
            return
        await self._limiter(request, response)


# Preconfigured rate limiter: 5 attempts per 5 minutes (300 seconds)
auth_limiter = SafeRateLimiter(times=5, seconds=300, identifier=auth_rate_limit_identifier)
