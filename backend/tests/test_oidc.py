import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest

from quip.models.user import User
from quip.services import oidc
from quip.services.auth import create_access_token

PUBLIC = "https://quip.example.test"
ISSUER = f"{PUBLIC}/api/oidc"
RAKAZO = "https://rakazo.example.test"
REDIRECT = f"{RAKAZO}/api/auth/callback/oidc"
SECRET = "s" * 40
VERIFIER = "v" * 64


def challenge(verifier: str = VERIFIER) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorize_params(**overrides) -> dict:
    params = {
        "client_id": oidc.CLIENT_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": "openid email profile",
        "state": "state-1",
        "nonce": "nonce-1",
        "code_challenge": challenge(),
        "code_challenge_method": "S256",
    }
    params.update(overrides)
    return {key: value for key, value in params.items() if value is not None}


def token_form(code: str, **overrides) -> dict:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER,
        "client_id": oidc.CLIENT_ID,
        "client_secret": SECRET,
    }
    form.update(overrides)
    return form


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_APP_URL", PUBLIC)
    monkeypatch.setenv("RAKAZO_URL", RAKAZO)
    monkeypatch.setenv("RAKAZO_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("OIDC_SIGNING_KEY_FILE", str(tmp_path / "oidc.pem"))
    oidc.signing_key.cache_clear()
    yield
    oidc.signing_key.cache_clear()


async def make_user(db_session, role="user", active=True):
    user = User(
        email=f"{role}{active}@quip.dev",
        username=f"{role}{active}",
        name="Имя Пользователя",
        role=role,
        is_active=active,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, {"Authorization": f"Bearer {create_access_token(str(user.id), role)}"}


async def get_code(client, headers, **overrides) -> str:
    response = await client.get("/api/oidc/authorize", params=authorize_params(**overrides), headers=headers)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return query["code"][0]


async def test_discovery_matches_the_issuer_exactly(client):
    response = await client.get("/api/oidc/.well-known/openid-configuration")
    assert response.status_code == 200
    document = response.json()
    assert document["issuer"] == ISSUER
    assert document["authorization_endpoint"] == f"{ISSUER}/authorize"
    assert document["token_endpoint"] == f"{ISSUER}/token"
    assert document["userinfo_endpoint"] == f"{ISSUER}/userinfo"
    assert document["jwks_uri"] == f"{ISSUER}/jwks"
    assert document["code_challenge_methods_supported"] == ["S256"]
    assert document["id_token_signing_alg_values_supported"] == ["RS256"]


@pytest.mark.parametrize("missing", ["PUBLIC_APP_URL", "RAKAZO_URL", "RAKAZO_OIDC_CLIENT_SECRET"])
async def test_every_endpoint_is_hidden_until_fully_configured(client, monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert (await client.get("/api/oidc/.well-known/openid-configuration")).status_code == 404
    assert (await client.get("/api/oidc/jwks")).status_code == 404
    assert (await client.get("/api/oidc/authorize", params=authorize_params())).status_code == 404
    assert (await client.post("/api/oidc/token", data=token_form("x"))).status_code == 404
    assert (await client.get("/api/oidc/userinfo")).status_code == 404


async def test_short_client_secret_keeps_the_provider_disabled(client, monkeypatch):
    monkeypatch.setenv("RAKAZO_OIDC_CLIENT_SECRET", "short")
    assert (await client.get("/api/oidc/.well-known/openid-configuration")).status_code == 404


async def test_code_flow_issues_a_signed_id_token_for_the_quip_user(client, db_session):
    user, headers = await make_user(db_session)
    response = await client.get("/api/oidc/authorize", params=authorize_params(), headers=headers)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT
    query = parse_qs(location.query)
    assert query["state"] == ["state-1"]
    assert query["iss"] == [ISSUER]

    tokens = await client.post("/api/oidc/token", data=token_form(query["code"][0]))
    assert tokens.status_code == 200
    assert tokens.headers["cache-control"] == "no-store"
    body = tokens.json()
    assert body["token_type"] == "Bearer"

    keys = (await client.get("/api/oidc/jwks")).json()["keys"]
    header = jwt.get_unverified_header(body["id_token"])
    assert header["alg"] == "RS256"
    key = next(item for item in keys if item["kid"] == header["kid"])
    claims = jwt.decode(
        body["id_token"], jwt.PyJWK.from_dict(key).key, algorithms=["RS256"], audience=oidc.CLIENT_ID, issuer=ISSUER
    )
    assert claims["sub"] == str(user.id)
    assert claims["nonce"] == "nonce-1"
    assert claims["email"] == user.email
    assert claims["name"] == user.name
    # Quip does not prove mailbox ownership at registration.
    assert claims["email_verified"] is False


async def test_jwks_never_exposes_private_key_material(client):
    keys = (await client.get("/api/oidc/jwks")).json()["keys"]
    assert keys
    for key in keys:
        assert not {"d", "p", "q", "dp", "dq", "qi"} & set(key)


async def test_signing_key_survives_restart_and_is_private(client, tmp_path):
    first = (await client.get("/api/oidc/jwks")).json()
    assert (tmp_path / "oidc.pem").stat().st_mode & 0o777 == 0o600
    oidc.signing_key.cache_clear()
    assert (await client.get("/api/oidc/jwks")).json() == first


async def test_userinfo_returns_the_same_subject(client, db_session):
    user, headers = await make_user(db_session)
    code = await get_code(client, headers)
    access = (await client.post("/api/oidc/token", data=token_form(code))).json()["access_token"]
    info = await client.get("/api/oidc/userinfo", headers={"Authorization": f"Bearer {access}"})
    assert info.status_code == 200
    assert info.json()["sub"] == str(user.id)
    assert info.json()["email"] == user.email


async def test_userinfo_rejects_a_quip_session_token(client, db_session):
    _, headers = await make_user(db_session)
    assert (await client.get("/api/oidc/userinfo", headers=headers)).status_code == 401


async def test_userinfo_rejects_an_id_token(client, db_session):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    id_token = (await client.post("/api/oidc/token", data=token_form(code))).json()["id_token"]
    response = await client.get("/api/oidc/userinfo", headers={"Authorization": f"Bearer {id_token}"})
    assert response.status_code == 401


async def test_userinfo_stops_working_when_the_user_is_blocked(client, db_session):
    user, headers = await make_user(db_session)
    code = await get_code(client, headers)
    access = (await client.post("/api/oidc/token", data=token_form(code))).json()["access_token"]
    user.is_active = False
    await db_session.commit()
    info = await client.get("/api/oidc/userinfo", headers={"Authorization": f"Bearer {access}"})
    assert info.status_code == 401


async def test_code_works_only_once(client, db_session):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    assert (await client.post("/api/oidc/token", data=token_form(code))).status_code == 200
    replay = await client.post("/api/oidc/token", data=token_form(code))
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


async def test_expired_code_is_rejected(client, db_session, monkeypatch):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    monkeypatch.setattr(oidc, "now", lambda: oidc.int_now() + oidc.CODE_TTL_SECONDS + 1)
    response = await client.post("/api/oidc/token", data=token_form(code))
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_wrong_verifier_fails_and_burns_the_code(client, db_session):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    wrong = await client.post("/api/oidc/token", data=token_form(code, code_verifier="w" * 64))
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"
    assert (await client.post("/api/oidc/token", data=token_form(code))).status_code == 400


async def test_token_requires_the_client_secret(client, db_session):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    response = await client.post("/api/oidc/token", data=token_form(code, client_secret="x" * 40))
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    # A rejected client must not consume the code.
    assert (await client.post("/api/oidc/token", data=token_form(code))).status_code == 200


async def test_token_accepts_http_basic_client_authentication(client, db_session):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    form = token_form(code)
    del form["client_id"], form["client_secret"]
    response = await client.post("/api/oidc/token", data=form, auth=(oidc.CLIENT_ID, SECRET))
    assert response.status_code == 200


async def test_token_rejects_a_different_redirect_uri(client, db_session):
    _, headers = await make_user(db_session)
    code = await get_code(client, headers)
    response = await client.post("/api/oidc/token", data=token_form(code, redirect_uri=f"{REDIRECT}x"))
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_user_blocked_after_authorize_cannot_redeem_the_code(client, db_session):
    user, headers = await make_user(db_session)
    code = await get_code(client, headers)
    user.is_active = False
    await db_session.commit()
    response = await client.post("/api/oidc/token", data=token_form(code))
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.parametrize(
    "overrides",
    [
        {"redirect_uri": "https://evil.example.test/api/auth/callback/oidc"},
        {"redirect_uri": f"{REDIRECT}/extra"},
        {"redirect_uri": None},
        {"client_id": "someone-else"},
    ],
)
async def test_unverified_client_or_redirect_never_redirects(client, db_session, overrides):
    _, headers = await make_user(db_session)
    response = await client.get("/api/oidc/authorize", params=authorize_params(**overrides), headers=headers)
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"scope": "email"}, "invalid_scope"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": None}, "invalid_request"),
        ({"code_challenge": "short"}, "invalid_request"),
    ],
)
async def test_invalid_requests_return_an_error_to_the_client(client, db_session, overrides, error):
    _, headers = await make_user(db_session)
    response = await client.get("/api/oidc/authorize", params=authorize_params(**overrides), headers=headers)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == [error]
    assert query["state"] == ["state-1"]
    assert "code" not in query


async def test_anonymous_browser_is_sent_to_login_and_back(client):
    response = await client.get("/api/oidc/authorize", params=authorize_params())
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.path == "/auth/login"
    assert not location.netloc
    back = parse_qs(location.query)["next"][0]
    assert back.startswith("/api/oidc/authorize?")
    assert parse_qs(urlsplit(back).query)["state"] == ["state-1"]


async def test_prompt_none_without_a_session_reports_login_required(client):
    response = await client.get("/api/oidc/authorize", params=authorize_params(prompt="none"))
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert response.headers["location"].startswith(REDIRECT)
    assert query["error"] == ["login_required"]


@pytest.mark.parametrize("overrides", [{"prompt": "login"}, {"max_age": "0"}])
async def test_fresh_login_requests_are_refused_rather_than_faked(client, db_session, overrides):
    # Quip's session does not record when the password was entered, so it cannot
    # honestly assert auth_time. Rakazo's reauthentication relies on that claim.
    _, headers = await make_user(db_session)
    response = await client.get("/api/oidc/authorize", params=authorize_params(**overrides), headers=headers)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == ["login_required"]
    assert "code" not in query


@pytest.mark.parametrize(("role", "active"), [("pending", True), ("user", False)])
async def test_blocked_and_pending_users_get_no_code(client, db_session, role, active):
    _, headers = await make_user(db_session, role=role, active=active)
    response = await client.get("/api/oidc/authorize", params=authorize_params(), headers=headers)
    assert response.status_code == 302
    assert urlsplit(response.headers["location"]).path == "/auth/login"


async def test_features_expose_the_rakazo_address_only_when_enabled(client, db_session, monkeypatch):
    _, headers = await make_user(db_session)
    assert (await client.get("/api/models/features", headers=headers)).json()["rakazo_url"] == RAKAZO
    monkeypatch.delenv("RAKAZO_OIDC_CLIENT_SECRET")
    assert (await client.get("/api/models/features", headers=headers)).json()["rakazo_url"] == ""
