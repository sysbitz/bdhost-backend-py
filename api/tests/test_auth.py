import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_full_flow(api_client: AsyncClient) -> None:
    # 1. Register
    reg_payload = {
        "email": "developer@example.com",
        "password": "Password123!",
        "full_name": "Test Developer",
    }
    reg_res = await api_client.post("/auth/register", json=reg_payload)
    assert reg_res.status_code == 201
    user_data = reg_res.json()
    assert user_data["email"] == "developer@example.com"
    assert "id" in user_data

    # 2. Login
    login_payload = {
        "email": "developer@example.com",
        "password": "Password123!",
    }
    login_res = await api_client.post("/auth/login", json=login_payload)
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert "access_token" in login_data
    access_token = login_data["access_token"]
    assert "refresh_token" in login_res.cookies
    refresh_token = login_res.cookies["refresh_token"]

    # 3. Access protected route (/auth/me)
    me_res = await api_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "developer@example.com"
    assert me_data["full_name"] == "Test Developer"

    # 4. Refresh token
    api_client.cookies.set("refresh_token", refresh_token)
    refresh_res = await api_client.post("/auth/refresh")
    assert refresh_res.status_code == 200
    new_data = refresh_res.json()
    assert "access_token" in new_data
    assert new_data["access_token"] != access_token

    # 5. Logout
    new_refresh_token = refresh_res.cookies.get("refresh_token") or refresh_token
    api_client.cookies.set("refresh_token", new_refresh_token)
    logout_res = await api_client.post("/auth/logout")
    assert logout_res.status_code == 200
