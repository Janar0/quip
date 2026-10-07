"""Safe model successor matching and admin-driven update behavior."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from quip.core.config import get_setting, set_setting
from quip.models.chat import Chat, Message
from quip.models.config import Config
from quip.models.user import User
from quip.models.workspace import Workspace
from quip.routers import models as models_router
from quip.services import model_updater


def model(model_id, *, name=None, prompt="0.000001", completion="0.000002"):
    return {
        "id": model_id,
        "name": name or model_id,
        "created": 100,
        "pricing": {"prompt": prompt, "completion": completion},
    }


def test_resolves_only_newer_same_vendor_family_and_tier_successor():
    old = model("z-ai/glm-5.2")
    latest = model("z-ai/glm-6")
    catalog = [
        old,
        latest,
        model("z-ai/glm-6-air"),
        model("z-ai/glm-5.1"),
        model("qwen/qwen-6"),
        model("anthropic/glm-6"),
    ]

    result = model_updater.resolve_successor_mappings([old["id"]], catalog, {old["id"]: latest["id"]})

    assert result == {"replacements": {old["id"]: latest["id"]}, "skipped": []}


def test_keeps_parameter_count_as_part_of_the_model_tier():
    source = "meta-llama/llama-3.1-70b-instruct"
    same_tier = "meta-llama/llama-3.3-70b-instruct"
    different_tier = "meta-llama/llama-3.3-8b-instruct"

    result = model_updater.resolve_successor_mappings(
        [source], [model(source), model(same_tier), model(different_tier)], {source: same_tier}
    )

    assert result == {"replacements": {source: same_tier}, "skipped": []}


@pytest.mark.parametrize(
    ("proposed", "reason"),
    [
        ("z-ai/glm-5.1", "backwards"),
        ("z-ai/glm-5.3", "not_latest"),
        ("z-ai/glm-6-air", "unrelated"),
        ("other/glm-6", "unrelated"),
        ("z-ai/nonexistent-6", "target_not_in_catalog"),
    ],
)
def test_rejects_invalid_successor_suggestions(proposed, reason):
    source = "z-ai/glm-5.2"
    catalog = [
        model(source),
        model("z-ai/glm-5.1"),
        model("z-ai/glm-5.3"),
        model("z-ai/glm-6"),
        model("z-ai/glm-6-air"),
        model("other/glm-6"),
    ]

    result = model_updater.resolve_successor_mappings([source], catalog, {source: proposed})

    assert result["replacements"] == {}
    assert result["skipped"] == [{"model_id": source, "reason": reason}]


def test_skips_ambiguous_latest_versions():
    source = "z-ai/glm-5.2"
    catalog = [model(source), model("z-ai/glm-6"), model("z-ai/glm-6.0")]

    result = model_updater.resolve_successor_mappings([source], catalog, {source: "z-ai/glm-6"})

    assert result["replacements"] == {}
    assert result["skipped"] == [{"model_id": source, "reason": "ambiguous"}]


def test_rejects_duplicate_source_entries_even_if_first_entry_has_no_target():
    source = "z-ai/glm-5.2"
    target = "z-ai/glm-6"

    suggestions, duplicates = model_updater.parse_mapping_response(
        json.dumps({"replacements": [{"from": source}, {"from": source, "to": target}]})
    )

    assert suggestions == {}
    assert duplicates == {source}


def test_invalidating_openrouter_models_keeps_ollama_cache(monkeypatch):
    monkeypatch.setitem(models_router._cache, "openrouter", (0, [model("z-ai/glm-6")]))
    monkeypatch.setitem(models_router._cache, "ollama:http://localhost:11434", (0, [{"id": "ollama/llama3"}]))

    models_router.invalidate_openrouter_models_cache()

    assert "openrouter" not in models_router._cache
    assert models_router._cache["ollama:http://localhost:11434"][1] == [{"id": "ollama/llama3"}]


def test_rewrites_only_model_references_and_preserves_colliding_alias():
    source = "z-ai/glm-5.2"
    target = "z-ai/glm-6"
    settings = {
        "model_whitelist": [source, "other/model", target],
        "model_aliases": {source: "Old name", target: "Chosen name"},
        "default_model": source,
        "search_model": "other/search",
        "rag_enabled": "true",
        "system_prompt": "keep this",
    }

    updated, changed = model_updater.apply_model_replacements(settings, {source: target})

    assert updated["model_whitelist"] == [target, "other/model"]
    assert updated["default_model"] == target
    assert updated["search_model"] == "other/search"
    assert updated["model_aliases"] == {source: "Old name", target: "Chosen name"}
    assert updated["rag_enabled"] == "true"
    assert updated["system_prompt"] == "keep this"
    assert changed == ["model_whitelist", "default_model"]


def test_copies_model_alias_to_successor_without_changing_historical_alias():
    source = "z-ai/glm-5.2"
    target = "z-ai/glm-6"

    updated, changed = model_updater.apply_model_replacements(
        {"model_aliases": {source: "Preferred name"}}, {source: target}
    )

    assert updated["model_aliases"] == {source: "Preferred name", target: "Preferred name"}
    assert changed == ["model_aliases"]


@pytest.mark.asyncio
async def test_admin_update_fetches_catalog_maps_references_and_reports_price_change(
    client, auth_headers, db_session, monkeypatch
):
    source = model("z-ai/glm-5.2", prompt="0.000001", completion="0.000002")
    target = model("z-ai/glm-6", prompt="0.000003", completion="0.000005")
    set_setting("openrouter_api_key", "test-only-key")
    set_setting("model_whitelist", json.dumps([source["id"]]))
    set_setting("default_model", source["id"])
    set_setting("title_model", target["id"])
    set_setting("model_aliases", "{}")
    set_setting("system_prompt", "keep this prompt")
    set_setting("rag_enabled", "true")

    async def catalog(_key):
        return [source, target]

    monkeypatch.setattr("quip.routers.admin.or_list_models", catalog)
    cache_invalidations = []
    monkeypatch.setattr(
        "quip.routers.admin.invalidate_openrouter_models_cache",
        lambda: cache_invalidations.append(True),
        raising=False,
    )

    requests = []

    def handle(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"replacements": [{"from": source["id"], "to": target["id"]}]})}}
                ]
            },
        )

    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return original_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(model_updater.httpx, "AsyncClient", mock_client)

    admin = (await db_session.execute(select(User).where(User.role == "admin"))).scalar_one()
    admin.settings = {"default_model": source["id"], "locale": "ru"}
    workspace = Workspace(owner_id=admin.id, name="Personal", default_model=source["id"])
    historical_chat = Chat(user_id=admin.id, title="Old chat", model=source["id"])
    db_session.add(historical_chat)
    await db_session.flush()
    historical_message = Message(
        chat_id=historical_chat.id,
        role="assistant",
        model=source["id"],
        content="Historical answer",
    )
    db_session.add(historical_message)
    db_session.add(workspace)
    await db_session.commit()

    response = await client.post("/api/admin/models/update", headers=auth_headers)

    assert response.status_code == 200
    assert cache_invalidations == [True]
    payload = response.json()
    assert payload["models"] == [
        {"id": source["id"], "name": source["id"]},
        {"id": target["id"], "name": target["id"]},
    ]
    assert payload["updated"][0]["old_id"] == source["id"]
    assert payload["updated"][0]["new_id"] == target["id"]
    assert payload["updated"][0]["price_change"]["prompt"] == {
        "before": "0.000001",
        "after": "0.000003",
        "percent_change": "200",
    }
    assert payload["skipped"] == [{"model_id": target["id"], "reason": "no_successor"}]
    assert requests[0].headers["Authorization"] == "Bearer test-only-key"

    assert payload["settings"]["model_whitelist"] == [target["id"]]
    assert payload["settings"]["default_model"] == target["id"]

    await db_session.refresh(admin)
    await db_session.refresh(workspace)
    await db_session.refresh(historical_chat)
    await db_session.refresh(historical_message)
    assert admin.settings == {"default_model": target["id"], "locale": "ru"}
    assert workspace.default_model == target["id"]
    assert historical_chat.model == source["id"]
    assert historical_message.model == source["id"]
    assert historical_message.content == "Historical answer"

    saved_config = (await db_session.execute(select(Config).where(Config.id == 1))).scalar_one()
    assert json.loads(saved_config.data["model_whitelist"]) == [target["id"]]
    assert saved_config.data["system_prompt"] == "keep this prompt"
    assert saved_config.data["rag_enabled"] == "true"


@pytest.mark.asyncio
async def test_empty_whitelist_means_all_models_remain_allowed(client, auth_headers, monkeypatch):
    set_setting("openrouter_api_key", "test-only-key")
    set_setting("model_whitelist", "[]")
    set_setting("default_model", "")
    set_setting("title_model", "")

    async def catalog(_key):
        return [model("z-ai/glm-6")]

    monkeypatch.setattr("quip.routers.admin.or_list_models", catalog)
    monkeypatch.setattr(
        model_updater,
        "request_successor_mappings",
        lambda *_args, **_kwargs: pytest.fail("empty allowlist must not map the full catalog"),
    )

    response = await client.post("/api/admin/models/update", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["updated"] == []
    assert response.json()["skipped"]
    assert response.json()["models"] == [{"id": "z-ai/glm-6", "name": "z-ai/glm-6"}]
    settings_response = await client.get("/api/admin/settings", headers=auth_headers)
    assert settings_response.json()["model_whitelist"] == []


@pytest.mark.asyncio
async def test_catalog_failure_returns_error_without_changing_saved_selection(
    client, auth_headers, db_session, monkeypatch
):
    source = "z-ai/glm-5.2"
    set_setting("openrouter_api_key", "test-only-key")
    set_setting("model_whitelist", json.dumps([source]))
    set_setting("default_model", source)

    async def empty_catalog(_key):
        return []

    monkeypatch.setattr("quip.routers.admin.or_list_models", empty_catalog)

    response = await client.post("/api/admin/models/update", headers=auth_headers)

    assert response.status_code == 502
    assert "nothing was changed" in response.json()["detail"]
    assert get_setting("model_whitelist") == json.dumps([source])
    assert get_setting("default_model") == source
    assert (await db_session.execute(select(Config).where(Config.id == 1))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_mapping_failure_leaves_saved_model_references_unchanged(client, auth_headers, db_session, monkeypatch):
    source = "z-ai/glm-5.2"
    target = "z-ai/glm-6"
    set_setting("openrouter_api_key", "test-only-key")
    set_setting("model_whitelist", json.dumps([source]))
    set_setting("default_model", source)

    async def catalog(_key):
        return [model(source), model(target)]

    async def mapping_failure(*_args, **_kwargs):
        raise model_updater.ModelMappingError("The model service could not complete the mapping.")

    monkeypatch.setattr("quip.routers.admin.or_list_models", catalog)
    monkeypatch.setattr(model_updater, "request_successor_mappings", mapping_failure)

    admin = (await db_session.execute(select(User).where(User.role == "admin"))).scalar_one()
    admin.settings = {"default_model": source, "locale": "ru"}
    workspace = Workspace(owner_id=admin.id, name="Personal", default_model=source)
    db_session.add(workspace)
    await db_session.commit()

    response = await client.post("/api/admin/models/update", headers=auth_headers)

    assert response.status_code == 502
    assert "could not complete the mapping" in response.json()["detail"]
    assert get_setting("model_whitelist") == json.dumps([source])
    assert get_setting("default_model") == source
    await db_session.refresh(admin)
    await db_session.refresh(workspace)
    assert admin.settings == {"default_model": source, "locale": "ru"}
    assert workspace.default_model == source
    assert (await db_session.execute(select(Config).where(Config.id == 1))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_model_update_requires_admin(client):
    response = await client.post("/api/admin/models/update")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_model_update_rejects_changed_settings_without_partial_updates(
    client, auth_headers, db_session, monkeypatch
):
    source = "z-ai/glm-5.2"
    target = "z-ai/glm-6"
    concurrent_choice = "other/provider-1"
    set_setting("openrouter_api_key", "test-only-key")
    set_setting("model_whitelist", json.dumps([source]))
    set_setting("default_model", source)
    set_setting("title_model", target)

    async def catalog(_key):
        return [model(source), model(target)]

    async def map_after_concurrent_setting_change(*_args, **_kwargs):
        async def persist_fixture_settings():
            from quip.core.config import get_all_settings

            config = (await db_session.execute(select(Config).where(Config.id == 1))).scalar_one_or_none()
            data = dict(config.data) if config and isinstance(config.data, dict) else {}
            data.update(get_all_settings())
            if config:
                config.data = data
                config.version = (config.version or 0) + 1
            else:
                db_session.add(Config(id=1, data=data, version=1))
            await db_session.commit()

        monkeypatch.setattr("quip.routers.admin.save_settings", persist_fixture_settings)
        settings_response = await client.put(
            "/api/admin/settings",
            headers=auth_headers,
            json={"default_model": concurrent_choice},
        )
        assert settings_response.status_code == 200
        return {source: target}, set()

    monkeypatch.setattr("quip.routers.admin.or_list_models", catalog)
    monkeypatch.setattr(
        model_updater,
        "request_successor_mappings",
        map_after_concurrent_setting_change,
    )
    admin = (await db_session.execute(select(User).where(User.role == "admin"))).scalar_one()
    admin.settings = {"default_model": source, "locale": "ru"}
    workspace = Workspace(owner_id=admin.id, name="Concurrent", default_model=source)
    db_session.add(workspace)
    await db_session.commit()

    response = await client.post("/api/admin/models/update", headers=auth_headers)

    assert response.status_code == 409
    assert get_setting("default_model") == concurrent_choice
    assert get_setting("model_whitelist") == json.dumps([source])
    await db_session.refresh(admin)
    await db_session.refresh(workspace)
    assert admin.settings == {"default_model": source, "locale": "ru"}
    assert workspace.default_model == source
    saved_config = (await db_session.execute(select(Config).where(Config.id == 1))).scalar_one()
    assert saved_config.data["default_model"] == concurrent_choice
    assert json.loads(saved_config.data["model_whitelist"]) == [source]


@pytest.mark.asyncio
async def test_concurrent_model_update_request_does_not_repeat_remote_mapping(client, auth_headers, monkeypatch):
    source = "z-ai/glm-5.2"
    target = "z-ai/glm-6"
    set_setting("openrouter_api_key", "test-only-key")
    set_setting("model_whitelist", json.dumps([source]))
    set_setting("default_model", source)
    set_setting("title_model", target)

    async def catalog(_key):
        return [model(source), model(target)]

    mapping_started = asyncio.Event()
    allow_mapping = asyncio.Event()
    mapping_calls = 0

    async def slow_mapping(*_args, **_kwargs):
        nonlocal mapping_calls
        mapping_calls += 1
        mapping_started.set()
        await allow_mapping.wait()
        return {source: target}, set()

    monkeypatch.setattr("quip.routers.admin.or_list_models", catalog)
    monkeypatch.setattr(model_updater, "request_successor_mappings", slow_mapping)

    first_request = asyncio.create_task(client.post("/api/admin/models/update", headers=auth_headers))
    await asyncio.wait_for(mapping_started.wait(), timeout=5)
    second_response = await client.post("/api/admin/models/update", headers=auth_headers)
    allow_mapping.set()
    first_response = await first_request

    assert second_response.status_code == 409
    assert first_response.status_code == 200
    assert mapping_calls == 1
