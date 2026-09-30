import json

from quip.services.chat_runs import bounded_snapshot
from quip.services.research.sources import validated_search_sources


def test_long_citation_url_is_never_rewritten_and_oversize_snapshot_is_marked():
    url = "https://example.org/" + "x" * 2110 + "#section"
    result = validated_search_sources(json.dumps({"results": [{"url": url, "title": "Long URL"}]}))

    assert result[0]["url"] == url
    snapshot = bounded_snapshot({"sources": result})
    assert snapshot["sources"] == []
    assert snapshot["truncated"] is True
