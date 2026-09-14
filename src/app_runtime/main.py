from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app_runtime.resolver import extract_subdomain, resolve_app
from shared.cache.redis_client import close_redis
from shared.db.base import get_db_session
from shared.storage.r2_client import get_r2_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await close_redis()


def create_runtime_app() -> FastAPI:
    app = FastAPI(
        title="bdhost App Runtime",
        description="High-performance tenant resolver and file streaming edge",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "app-runtime"}

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def serve_tenant_request(
        request: Request,
        path: str = "",
        host: str | None = Header(default=None),
        db: AsyncSession = Depends(get_db_session),
    ) -> Response:
        subdomain = extract_subdomain(host or request.headers.get("host"))
        if not subdomain:
            return HTMLResponse(
                content="""<!DOCTYPE html>
<html>
<head><title>bdhost Edge</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
  <h1>bdhost Tenant Edge</h1>
  <p>Please access hosted sites via your subdomain URL (e.g. <code>https://&lt;subdomain&gt;.bdappshub.com</code>).</p>
</body>
</html>""",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        app_data = await resolve_app(subdomain=subdomain, db=db)
        if not app_data:
            return HTMLResponse(
                content=f"""<!DOCTYPE html>
<html>
<head><title>404 - Site Not Found</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
  <h1>404 - Site Not Found</h1>
  <p>The subdomain <strong>{subdomain}</strong> does not exist or has not been deployed yet.</p>
</body>
</html>""",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Check tenant status
        if app_data["status"] == "suspended":
            return HTMLResponse(
                content=f"""<!DOCTYPE html>
<html>
<head><title>403 - Site Suspended</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
  <h1>Site Suspended</h1>
  <p>The site <strong>{subdomain}</strong> is currently suspended. Please contact support.</p>
</body>
</html>""",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if app_data["status"] != "active":
            return HTMLResponse(
                content="""<!DOCTYPE html>
<html>
<head><title>Site Unavailable</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
  <h1>Site Unavailable</h1>
  <p>This site is not currently active.</p>
</body>
</html>""",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        r2 = get_r2_client()
        clean_path = path.lstrip("/")
        custom_index = app_data.get("custom_index") or "index.html"

        if not clean_path or clean_path.endswith("/"):
            key = f"apps/{app_data['id']}/{clean_path}{custom_index}"
        else:
            key = f"apps/{app_data['id']}/{clean_path}"

        obj = await r2.get_object(key)

        # If not found and spa_fallback is enabled, try custom_index
        if obj is None and app_data.get("spa_fallback", False):
            fallback_key = f"apps/{app_data['id']}/{custom_index}"
            obj = await r2.get_object(fallback_key)

        if obj is None:
            return HTMLResponse(
                content="""<!DOCTYPE html>
<html>
<head><title>404 - File Not Found</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
  <h1>404 - File Not Found</h1>
  <p>The requested file does not exist.</p>
</body>
</html>""",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        etag = obj.get("etag", "")
        # Handle conditional requests (ETag caching)
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and etag and if_none_match.strip('"') == etag.strip('"'):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)

        headers = {
            "ETag": f'"{etag}"' if etag else "",
            "Cache-Control": "public, max-age=300",
        }
        if not etag:
            del headers["ETag"]

        if request.method == "HEAD":
            return Response(
                status_code=status.HTTP_200_OK,
                media_type=obj["content_type"],
                headers=headers,
            )

        return Response(
            content=obj["body"],
            status_code=status.HTTP_200_OK,
            media_type=obj["content_type"],
            headers=headers,
        )

    return app


app = create_runtime_app()
