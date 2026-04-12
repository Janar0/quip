from quip.services.auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_token


def test_hash_and_verify_password():
    password = "supersecret123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    token = create_access_token(user_id="abc-123", role="admin")
    payload = decode_token(token)
    assert payload["sub"] == "abc-123"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    token = create_refresh_token(user_id="abc-123")
    payload = decode_token(token)
    assert payload["sub"] == "abc-123"
    assert payload["type"] == "refresh"


def test_decode_invalid_token():
    payload = decode_token("not.a.valid.token")
    assert payload is None
