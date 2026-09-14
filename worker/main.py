import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from shared.cache.redis_client import close_redis
from shared.config import get_settings
from worker.tasks import recalc_quota, send_email

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    logger.info("Starting arq background worker...")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("Shutting down arq background worker...")
    await close_redis()


def get_redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [recalc_quota, send_email]
    # Run quota recalculation job daily at 02:00 UTC
    cron_jobs = [
        cron(recalc_quota, hour={2}, minute={0}),
    ]
    redis_settings = get_redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
