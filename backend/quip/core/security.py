"""Resolve the JWT signing key consistently for local and container startup."""

import os
import secrets
import tempfile
from pathlib import Path

_OLD_PLACEHOLDER = "dev-secret-change-in-production"
_MINIMUM_KEY_BYTES = 32


def _read_secret_file(path: Path) -> str:
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Cannot read JWT secret file: {path}") from exc
    if len(secret.encode("utf-8")) < _MINIMUM_KEY_BYTES or secret == _OLD_PLACEHOLDER:
        raise RuntimeError(f"JWT secret file is corrupted or contains an insecure key: {path}")
    return secret


def resolve_jwt_secret() -> str:
    """Prefer an explicit secure key, otherwise reuse or atomically publish one.

    The destination is created by linking a complete, flushed private temporary
    file. Concurrent processes either publish their candidate or read the winner;
    the persistent path never exposes an empty or partially written key.
    """
    configured = os.getenv("JWT_SECRET", "")
    if configured.strip() and configured.strip() != _OLD_PLACEHOLDER:
        if len(configured.encode("utf-8")) < _MINIMUM_KEY_BYTES:
            raise RuntimeError("JWT_SECRET must contain at least 32 UTF-8 bytes")
        return configured

    path = Path(os.getenv("JWT_SECRET_FILE") or Path(__file__).resolve().parents[2] / "data" / ".jwt_secret")
    try:
        return _read_secret_file(path)
    except FileNotFoundError:
        pass

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".jwt-secret-", dir=path.parent, delete=False
        )
        candidate_path = Path(handle.name)
        try:
            with handle:
                os.chmod(candidate_path, 0o600)
                handle.write(secrets.token_hex(32))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(candidate_path, path)
            except FileExistsError:
                pass
        finally:
            candidate_path.unlink()
        return _read_secret_file(path)
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Cannot initialize JWT secret file: {path}") from exc


if __name__ == "__main__":
    resolve_jwt_secret()
