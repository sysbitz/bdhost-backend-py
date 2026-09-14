import pytest
from httpx import AsyncClient


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
