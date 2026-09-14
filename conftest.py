import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import get_db
from api.main import app as api_app
from app_runtime.main import app as runtime_app
from shared.db.base import Base, get_db_session
from shared.db.models import Plan

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        # Seed default plan
        plan = Plan(
            name="Free",
            app_limit=5,
            storage_limit_mb=100,
            features={"custom_subdomain": True},
        )
        session.add(plan)
        await session.commit()
        yield session


class MockR2Client:
    def __init__(self) -> None:
        self.storage: dict[str, dict[str, Any]] = {}

    async def put_object(
        self,
        key: str,
        data: bytes | Any,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(data, bytes):
            data = data.read()
            if isinstance(data, str):
                data = data.encode("utf-8")
        self.storage[key] = {
            "body": data,
            "content_type": content_type or "application/octet-stream",
            "content_length": len(data),
            "etag": "test-etag",
            "metadata": metadata or {},
        }
        return {"ETag": "test-etag"}

    async def get_object(self, key: str) -> dict[str, Any] | None:
        return self.storage.get(key)

    async def delete_object(self, key: str) -> bool:
        if key in self.storage:
            del self.storage[key]
            return True
        return False

    async def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        results = []
        for k, v in self.storage.items():
            if k.startswith(prefix):
                results.append(
                    {
                        "key": k,
                        "size": len(v["body"]),
                        "last_modified": None,
                        "etag": v["etag"],
                    }
                )
        return results

    async def calculate_prefix_size(self, prefix: str) -> int:
        return sum(len(v["body"]) for k, v in self.storage.items() if k.startswith(prefix))

    async def delete_objects_by_prefix(self, prefix: str) -> int:
        keys_to_delete = [k for k in self.storage if k.startswith(prefix)]
        for k in keys_to_delete:
            del self.storage[k]
        return len(keys_to_delete)


@pytest.fixture(autouse=True)
def mock_external_services(monkeypatch):
    # Mock Redis Subdomain cache and Refresh token store
    redis_memory: dict[str, str] = {}

    async def mock_get_app_cache(subdomain: str):
        val = redis_memory.get(f"app:{subdomain.lower()}")
        if val == "__NOT_FOUND__":
            return "not_found"
        if val:
            return json.loads(val)
        return None

    async def mock_set_app_cache(subdomain: str, data: dict, ttl: int = 60):
        redis_memory[f"app:{subdomain.lower()}"] = json.dumps(data)

    async def mock_set_app_not_found(subdomain: str, ttl: int = 60):
        redis_memory[f"app:{subdomain.lower()}"] = "__NOT_FOUND__"

    async def mock_invalidate_app_cache(subdomain: str):
        redis_memory.pop(f"app:{subdomain.lower()}", None)

    async def mock_store_refresh_token(jti: str, user_id: str, ttl_seconds: int):
        redis_memory[f"refresh:{jti}"] = user_id

    async def mock_verify_refresh_token(jti: str):
        return redis_memory.get(f"refresh:{jti}")

    async def mock_revoke_refresh_token(jti: str):
        redis_memory.pop(f"refresh:{jti}", None)

    monkeypatch.setattr("shared.cache.redis_client.get_app_cache", mock_get_app_cache)
    monkeypatch.setattr("shared.cache.redis_client.set_app_cache", mock_set_app_cache)
    monkeypatch.setattr("shared.cache.redis_client.set_app_not_found", mock_set_app_not_found)
    monkeypatch.setattr("shared.cache.redis_client.invalidate_app_cache", mock_invalidate_app_cache)
    monkeypatch.setattr("shared.cache.redis_client.store_refresh_token", mock_store_refresh_token)
    monkeypatch.setattr(
        "shared.cache.redis_client.verify_refresh_token_in_cache", mock_verify_refresh_token
    )
    monkeypatch.setattr("shared.cache.redis_client.revoke_refresh_token", mock_revoke_refresh_token)

    monkeypatch.setattr("api.routers.auth.store_refresh_token", mock_store_refresh_token)
    monkeypatch.setattr("api.routers.auth.verify_refresh_token_in_cache", mock_verify_refresh_token)
    monkeypatch.setattr("api.routers.auth.revoke_refresh_token", mock_revoke_refresh_token)
    monkeypatch.setattr("api.services.app_service.invalidate_app_cache", mock_invalidate_app_cache)
    monkeypatch.setattr("app_runtime.resolver.get_app_cache", mock_get_app_cache)
    monkeypatch.setattr("app_runtime.resolver.set_app_cache", mock_set_app_cache)
    monkeypatch.setattr("app_runtime.resolver.set_app_not_found", mock_set_app_not_found)

    # Mock R2 Client
    mock_r2 = MockR2Client()
    monkeypatch.setattr("shared.storage.r2_client.get_r2_client", lambda: mock_r2)
    monkeypatch.setattr("api.services.file_service.get_r2_client", lambda: mock_r2)
    monkeypatch.setattr("app_runtime.main.get_r2_client", lambda: mock_r2)


@pytest.fixture
async def api_client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield test_session

    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_db_session] = override_get_db

    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    api_app.dependency_overrides.clear()


@pytest.fixture
async def runtime_client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield test_session

    runtime_app.dependency_overrides[get_db_session] = override_get_db

    transport = ASGITransport(app=runtime_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    runtime_app.dependency_overrides.clear()
