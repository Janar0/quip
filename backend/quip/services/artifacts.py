"""Artifact parser — extracts <artifact> tags from model output."""
import re
import hashlib
from uuid import uuid4


# Regex to match <artifact ...attributes...>content</artifact>
# Uses a more flexible attribute parser
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_TAG_RE = re.compile(
    r'<artifact\s+([^>]*)>(.*?)</artifact>',
    re.DOTALL,
)


def _parse_attrs(attr_str: str) -> dict[str, str]:
    return dict(_ATTR_RE.findall(attr_str))


def extract_artifacts(content: str) -> tuple[list[dict], str]:
    """Extract <artifact> tags from content.

    Returns (artifacts, cleaned_content) where cleaned_content has
    artifact blocks removed (frontend renders them from the artifacts array).
    """
    artifacts: list[dict] = []

    def replacer(match: re.Match) -> str:
        attrs = _parse_attrs(match.group(1))
        body = match.group(2).strip()

        identifier = attrs.get("identifier") or hashlib.md5(body.encode()).hexdigest()[:12]
        art_type = attrs.get("type", "code")
        title = attrs.get("title", "Artifact")
        language = attrs.get("language")

        artifact: dict = {
            "id": str(uuid4()),
            "identifier": identifier,
            "type": art_type,
            "title": title,
            "content": body,
            "version": 1,
        }
        if language:
            artifact["language"] = language

        artifacts.append(artifact)
        return ""

    cleaned = _TAG_RE.sub(replacer, content).strip()
    # Collapse excessive blank lines left after tag removal
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return artifacts, cleaned if artifacts else content
