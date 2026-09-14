from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.rate_limit import init_rate_limiter
from api.routers import account, apps, auth, billing, files
from shared.cache.redis_client import close_redis
from shared.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup actions
    await init_rate_limiter()
    yield
    # Shutdown actions
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="bdhost API",
        description="Core management API for bdhost (auth, apps, files, billing)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers
    app.include_router(auth.router)
    app.include_router(apps.router)
    app.include_router(files.router)
    app.include_router(billing.router)
    app.include_router(account.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "api"}

    return app


app = create_app()
