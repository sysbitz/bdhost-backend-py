import pytest
from httpx import AsyncClient

from src.app_runtime.resolver import extract_subdomain


def test_extract_subdomain_validation() -> None:
    # Valid platform subdomains
    assert extract_subdomain("my-site.bdappshub.com") == "my-site"
    assert extract_subdomain("app123.bdappshub.com:8080") == "app123"
    assert extract_subdomain("portfolio.bdappshub.com:443") == "portfolio"
    # Localhost in development environment
    assert extract_subdomain("my-app.localhost:8000") == "my-app"

    # Exact base domain or localhost (not a tenant)
    assert extract_subdomain("bdappshub.com") is None
    assert extract_subdomain("bdappshub.com:8080") is None
    assert extract_subdomain("localhost") is None
    assert extract_subdomain("127.0.0.1:8000") is None

    # Foreign domains
    assert extract_subdomain("evil.com") is None
    assert extract_subdomain("attacker.com:80") is None
    assert extract_subdomain("notbdappshub.com") is None
    assert extract_subdomain("mybdappshub.com") is None

    # Multi-level / nested subdomains
    assert extract_subdomain("foo.bar.bdappshub.com") is None
    assert extract_subdomain("a.b.c.bdappshub.com") is None

    # Malformed subdomains
    assert extract_subdomain("-leading-hyphen.bdappshub.com") is None
    assert extract_subdomain("trailing-hyphen-.bdappshub.com") is None
    assert extract_subdomain("bad_character$.bdappshub.com") is None

    # Reserved platform subdomains
    assert extract_subdomain("api.bdappshub.com") is None
    assert extract_subdomain("auth.bdappshub.com") is None
    assert extract_subdomain("admin.bdappshub.com") is None
    assert extract_subdomain("www.bdappshub.com") is None

    # None / empty
    assert extract_subdomain(None) is None
    assert extract_subdomain("") is None
    assert extract_subdomain("   ") is None


@pytest.mark.asyncio
async def test_runtime_health(runtime_client: AsyncClient) -> None:
    response = await runtime_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "app-runtime"


@pytest.mark.asyncio
async def test_runtime_missing_subdomain(runtime_client: AsyncClient) -> None:
    response = await runtime_client.get(
        "/",
        headers={"Host": "non-existent-app.bdappshub.com"},
    )
    assert response.status_code == 404
    assert "Site Not Found" in response.text


@pytest.mark.asyncio
async def test_runtime_rejects_foreign_and_invalid_hosts(runtime_client: AsyncClient) -> None:
    # Foreign host: evil.com
    res1 = await runtime_client.get("/", headers={"Host": "evil.com"})
    assert res1.status_code == 404
    assert "bdhost Tenant Edge" in res1.text

    # Exact base domain
    res2 = await runtime_client.get("/", headers={"Host": "bdappshub.com"})
    assert res2.status_code == 404
    assert "bdhost Tenant Edge" in res2.text

    # Nested subdomain
    res3 = await runtime_client.get("/", headers={"Host": "sub.nested.bdappshub.com"})
    assert res3.status_code == 404
    assert "bdhost Tenant Edge" in res3.text


@pytest.mark.asyncio
async def test_upload_and_resolve_flow(
    api_client: AsyncClient,
    runtime_client: AsyncClient,
) -> None:
    # 1. Register and login
    await api_client.post(
        "/auth/register",
        json={"email": "tenant@example.com", "password": "Password123!"},
    )
    login_res = await api_client.post(
        "/auth/login",
        json={"email": "tenant@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create app with subdomain "my-landing" and spa_fallback=True
    create_res = await api_client.post(
        "/apps",
        json={"subdomain": "my-landing"},
        headers=headers,
    )
    assert create_res.status_code == 201
    app_data = create_res.json()
    app_id = app_data["id"]

    # Enable SPA fallback
    patch_res = await api_client.patch(
        f"/apps/{app_id}",
        json={"spa_fallback": True},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["spa_fallback"] is True

    # 3. Upload index.html
    html_content = b"<html><body><h1>Hello from bdhost!</h1></body></html>"
    upload_res = await api_client.post(
        f"/apps/{app_id}/files",
        files={"file": ("index.html", html_content, "text/html")},
        data={"path": "index.html"},
        headers=headers,
    )
    assert upload_res.status_code == 201

    # 4. Resolve via app-runtime on root path
    runtime_res = await runtime_client.get(
        "/",
        headers={"Host": "my-landing.bdappshub.com"},
    )
    assert runtime_res.status_code == 200
    assert "Hello from bdhost!" in runtime_res.text
    assert "text/html" in runtime_res.headers.get("content-type", "")

    # 5. Test SPA fallback on non-existent path
    spa_res = await runtime_client.get(
        "/dashboard/settings/profile",
        headers={"Host": "my-landing.bdappshub.com"},
    )
    assert spa_res.status_code == 200
    assert "Hello from bdhost!" in spa_res.text


@pytest.mark.asyncio
async def test_path_traversal_prevention(
    api_client: AsyncClient,
    runtime_client: AsyncClient,
) -> None:
    # 1. Login with existing seeded or new user
    await api_client.post(
        "/auth/register",
        json={"email": "traversal@example.com", "password": "Password123!"},
    )
    login_res = await api_client.post(
        "/auth/login",
        json={"email": "traversal@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_res = await api_client.post(
        "/apps",
        json={"subdomain": "secure-app"},
        headers=headers,
    )
    assert create_res.status_code == 201
    app_id = create_res.json()["id"]

    # 2. Upload a valid index.html
    await api_client.post(
        f"/apps/{app_id}/files",
        files={"file": ("index.html", b"<h1>Secure App</h1>", "text/html")},
        data={"path": "index.html"},
        headers=headers,
    )

    # 3. Path traversal attempts via GET
    res1 = await runtime_client.get(
        "/../etc/passwd",
        headers={"Host": "secure-app.bdappshub.com"},
    )
    assert res1.status_code == 404

    res2 = await runtime_client.get(
        "/../../apps/other/index.html",
        headers={"Host": "secure-app.bdappshub.com"},
    )
    assert res2.status_code == 404

    res3 = await runtime_client.get(
        "/%2e%2e/%2e%2e/config.py",
        headers={"Host": "secure-app.bdappshub.com"},
    )
    assert res3.status_code == 404

    # 4. Attempting to set malicious custom_index should be rejected with 400
    patch_malicious = await api_client.patch(
        f"/apps/{app_id}",
        json={"custom_index": "../../evil.html"},
        headers=headers,
    )
    assert patch_malicious.status_code == 400
    assert "Invalid custom_index" in patch_malicious.text
