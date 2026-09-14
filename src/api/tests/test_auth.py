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


@pytest.mark.asyncio
async def test_admin_setup_one_time_and_panel_access(api_client: AsyncClient) -> None:
    # 1. Check initial setup status - no admin should exist in fresh test session
    status_res = await api_client.get("/auth/setup-status")
    assert status_res.status_code == 200
    assert status_res.json()["admin_setup_required"] is True

    # 2. Perform one-time admin setup
    setup_payload = {
        "email": "owner@bdappshub.com",
        "password": "MasterPassword123!",
        "full_name": "Platform Owner",
    }
    setup_res = await api_client.post("/auth/setup-admin", json=setup_payload)
    assert setup_res.status_code == 201
    setup_data = setup_res.json()
    assert setup_data["success"] is True
    assert setup_data["user"]["email"] == "owner@bdappshub.com"
    assert setup_data["user"]["role"] == "admin"
    admin_token = setup_data["access_token"]
    assert "refresh_token" in setup_res.cookies

    # 3. Check setup status after admin creation - setup must now be disabled
    status_res_after = await api_client.get("/auth/setup-status")
    assert status_res_after.status_code == 200
    assert status_res_after.json()["admin_setup_required"] is False

    # 4. Attempting to call setup-admin a second time must fail with 403 Forbidden
    second_attempt = await api_client.post(
        "/auth/setup-admin",
        json={
            "email": "hacker@evil.com",
            "password": "Password123!",
            "full_name": "Intruder",
        },
    )
    assert second_attempt.status_code == 403
    assert "permanently disabled" in second_attempt.json()["detail"].lower()

    # 5. Admin Panel access with admin token
    overview_res = await api_client.get(
        "/admin/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert overview_res.status_code == 200
    overview_data = overview_res.json()
    assert "total_users" in overview_data
    assert "total_apps" in overview_data
    assert overview_data["total_users"] >= 1

    users_res = await api_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert users_res.status_code == 200
    users_list = users_res.json()
    assert any(u["email"] == "owner@bdappshub.com" for u in users_list)

    # 6. Regular user cannot access admin panel
    user_reg = await api_client.post(
        "/auth/register",
        json={"email": "regular@example.com", "password": "Password123!"},
    )
    assert user_reg.status_code == 201
    user_login = await api_client.post(
        "/auth/login",
        json={"email": "regular@example.com", "password": "Password123!"},
    )
    regular_token = user_login.json()["access_token"]

    forbidden_res = await api_client.get(
        "/admin/overview",
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert forbidden_res.status_code == 403

    # 7. Unauthenticated user cannot access admin panel
    unauth_res = await api_client.get("/admin/overview")
    assert unauth_res.status_code == 401
