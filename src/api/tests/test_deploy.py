import io
import zipfile

import pytest
from httpx import AsyncClient


def create_mock_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_zip_deploy_flow(api_client: AsyncClient, runtime_client: AsyncClient) -> None:
    # 1. Register & login
    await api_client.post(
        "/auth/register",
        json={"email": "deployer@example.com", "password": "Password123!"},
    )
    login_res = await api_client.post(
        "/auth/login",
        json={"email": "deployer@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create app
    app_res = await api_client.post("/apps", json={"subdomain": "zip-demo"}, headers=headers)
    assert app_res.status_code == 201
    app_id = app_res.json()["id"]

    # 3. Test invalid zip (disallowed file extension)
    bad_zip = create_mock_zip({"index.html": b"<h1>Ok</h1>", "malware.exe": b"bad"})
    bad_deploy = await api_client.post(
        f"/apps/{app_id}/deploy",
        files={"file": ("site.zip", bad_zip, "application/zip")},
        headers=headers,
    )
    assert bad_deploy.status_code == 400
    assert "Disallowed" in bad_deploy.text or "disallowed" in bad_deploy.text

    # 4. Test valid zip deploy
    good_zip = create_mock_zip(
        {
            "index.html": b"<h1>Welcome to Zip App</h1>",
            "assets/style.css": b"body { background: #000; }",
        }
    )
    deploy_res = await api_client.post(
        f"/apps/{app_id}/deploy",
        files={"file": ("site.zip", good_zip, "application/zip")},
        headers=headers,
    )
    assert deploy_res.status_code == 200
    deploy_data = deploy_res.json()
    assert deploy_data["success"] is True
    assert deploy_data["deployed_files"] == 2

    # 5. List files
    list_res = await api_client.get(f"/apps/{app_id}/files", headers=headers)
    assert list_res.status_code == 200
    file_keys = [f["key"] for f in list_res.json()["files"]]
    assert "index.html" in file_keys
    assert "assets/style.css" in file_keys

    # 6. Verify serving via app-runtime
    page_res = await runtime_client.get("/", headers={"Host": "zip-demo.bdappshub.com"})
    assert page_res.status_code == 200
    assert "Welcome to Zip App" in page_res.text

    css_res = await runtime_client.get(
        "/assets/style.css", headers={"Host": "zip-demo.bdappshub.com"}
    )
    assert css_res.status_code == 200
    assert "background: #000" in css_res.text

    # 7. Delete file
    del_res = await api_client.delete(
        f"/apps/{app_id}/files?path=assets/style.css",
        headers=headers,
    )
    assert del_res.status_code == 204
