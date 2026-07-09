import pytest

from quip.core.config import set_setting
from quip.models.user import User
from quip.services.auth import create_access_token


@pytest.mark.asyncio
async def test_personal_workspace_exists_after_registration(client, auth_headers):
    response = await client.get("/api/workspaces", headers=auth_headers)

    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) == 1
    assert workspaces[0]["name"] == "Personal"
    assert workspaces[0]["is_personal"] is True


@pytest.mark.asyncio
async def test_workspace_scopes_chats_files_and_overview(
    client,
    auth_headers,
    tmp_upload_dir,
):
    set_setting("rag_enabled", "false")
    created = await client.post(
        "/api/workspaces",
        headers=auth_headers,
        json={
            "name": "Product alpha",
            "description": "One coherent project context",
            "instructions": "Prefer concise technical answers.",
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    chat = await client.post(
        "/api/chats",
        headers=auth_headers,
        json={"title": "Architecture", "workspace_id": workspace["id"]},
    )
    assert chat.status_code == 201
    assert chat.json()["workspace_id"] == workspace["id"]

    upload = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        data={"workspace_id": workspace["id"]},
        files=[("files", ("notes.txt", b"workspace knowledge", "text/plain"))],
    )
    assert upload.status_code == 200
    assert upload.json()["files"][0]["workspace_id"] == workspace["id"]

    listed = await client.get(
        f"/api/chats?workspace_id={workspace['id']}",
        headers=auth_headers,
    )
    assert [item["id"] for item in listed.json()] == [chat.json()["id"]]

    overview = await client.get(
        f"/api/workspaces/{workspace['id']}/overview",
        headers=auth_headers,
    )
    assert overview.status_code == 200
    body = overview.json()
    assert body["workspace"]["instructions"] == "Prefer concise technical answers."
    assert body["chats"][0]["title"] == "Architecture"
    assert body["files"][0]["filename"] == "notes.txt"


@pytest.mark.asyncio
async def test_workspace_is_not_visible_to_another_tenant(
    client,
    auth_headers,
    db_session,
):
    created = await client.post(
        "/api/workspaces",
        headers=auth_headers,
        json={"name": "Owner only"},
    )
    workspace_id = created.json()["id"]

    other = User(
        email="workspace-other@test.dev",
        username="workspace-other",
        name="Workspace Other",
        role="user",
    )
    db_session.add(other)
    await db_session.commit()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(str(other.id), other.role)}"
    }

    denied = await client.get(
        f"/api/workspaces/{workspace_id}",
        headers=other_headers,
    )
    assert denied.status_code == 404

    denied_chat = await client.post(
        "/api/chats",
        headers=other_headers,
        json={"title": "Intrusion", "workspace_id": workspace_id},
    )
    assert denied_chat.status_code == 404


@pytest.mark.asyncio
async def test_personal_workspace_cannot_be_deleted(client, auth_headers):
    workspaces = (await client.get("/api/workspaces", headers=auth_headers)).json()
    personal_id = next(item["id"] for item in workspaces if item["is_personal"])

    response = await client.delete(
        f"/api/workspaces/{personal_id}",
        headers=auth_headers,
    )

    assert response.status_code == 400
