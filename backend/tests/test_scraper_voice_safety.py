import pytest


@pytest.mark.asyncio
async def test_read_url_validates_original_target_before_jina(client, monkeypatch):
    from quip.services import scraper

    called = False

    async def forbidden_target(url):
        assert url == "http://127.0.0.1/admin"
        raise ValueError("URL resolves to a non-public network address")

    async def never_read(*_args, **_kwargs):
        nonlocal called
        called = True
        return "unexpected"

    monkeypatch.setattr(scraper, "validate_outbound_url", forbidden_target, raising=False)
    monkeypatch.setattr(scraper, "_jina_reader", never_read)
    monkeypatch.setattr(scraper, "_direct_fetch", never_read)

    with pytest.raises(ValueError, match="non-public"):
        await scraper.read_url("http://127.0.0.1/admin")
    assert called is False
