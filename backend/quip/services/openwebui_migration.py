"""
Auto-migration from Open WebUI SQLite database.

Runs once at startup when webui.db is detected alongside quip.db.
Creates a clean QUIP schema — no open-webui legacy tables.

Detection order:
  1. $OPENWEBUI_DB env var
  2. same directory as quip.db / webui.db
  3. ./webui.db (cwd)

Migration is idempotent: a .migrated marker file prevents re-runs.
"""
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from quip.database import async_session, DATABASE_URL
from quip.models.user import User, Auth
from quip.models.chat import Chat, Message

logger = logging.getLogger(__name__)

MARKER_FILENAME = "webui.db.migrated"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _quip_db_dir() -> Path:
    url = DATABASE_URL
    if "///" in url:
        raw = url.split("///")[1]
        p = Path(raw)
        return (p.parent if not p.is_dir() else p).resolve()
    return Path(".").resolve()


def _find_webui_db() -> Path | None:
    env = os.getenv("OPENWEBUI_DB")
    if env:
        p = Path(env)
        return p.resolve() if p.exists() else None

    candidates = [
        _quip_db_dir() / "webui.db",
        Path("webui.db").resolve(),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _is_openwebui_db(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path))
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in c.fetchall()}
        conn.close()
        return {"user", "auth", "chat"}.issubset(tables)
    except Exception:
        return False


def _marker_path(webui_path: Path) -> Path:
    return webui_path.parent / MARKER_FILENAME


def _already_migrated(webui_path: Path) -> bool:
    return _marker_path(webui_path).exists()


def _write_marker(webui_path: Path, stats: dict) -> None:
    _marker_path(webui_path).write_text(
        json.dumps({
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "source": str(webui_path),
            **stats,
        }, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(val) -> datetime:
    if val is None:
        return datetime.now(timezone.utc)
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(float(val), tz=timezone.utc)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _uid(val) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


def _json_field(val) -> dict | list | None:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            pass
    return None


def _decode_content(raw) -> str:
    """open-webui stores content as JSON-encoded string — decode if needed."""
    if raw is None:
        return ""
    text = _extract_text(raw)
    if not text:
        return ""
    # Try JSON decode: '"actual text"' or '["block1","block2"]'
    stripped = text.strip()
    if stripped.startswith(('"', '[', '{')):
        try:
            decoded = json.loads(stripped)
            return _extract_text(decoded)
        except Exception:
            pass
    return text


def _extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_migration_if_needed() -> None:
    webui_path = _find_webui_db()
    if not webui_path:
        searched = [_quip_db_dir() / "webui.db", Path("webui.db").resolve()]
        print(f"[migration] No webui.db found (searched: {', '.join(str(p) for p in searched)})")
        return

    if not _is_openwebui_db(webui_path):
        print(f"[migration] Found {webui_path} but it doesn't look like an open-webui DB — skipping")
        return

    if _already_migrated(webui_path):
        print(f"[migration] Already done (marker: {_marker_path(webui_path)}) — skipping")
        return

    # Hard stop: don't touch a quip.db that already has data
    async with async_session() as db:
        from sqlalchemy import func, select
        from quip.models.user import User as _User
        result = await db.execute(select(func.count()).select_from(_User))
        existing_users = result.scalar_one()
    if existing_users > 0:
        print(
            f"[migration] quip.db already has {existing_users} user(s) — skipping. "
            f"To force, delete {_marker_path(webui_path)} and set OPENWEBUI_MIGRATE_FORCE=1"
        )
        # Write marker so we don't check again on every restart
        _write_marker(webui_path, {"skipped_reason": "quip.db already has data"})
        return

    print(f"[migration] Starting Open WebUI migration from {webui_path} ...")

    conn = sqlite3.connect(str(webui_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Detect available tables once
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    db_tables = {r[0] for r in cur.fetchall()}

    stats = {"users": 0, "auths": 0, "chats": 0, "messages": 0, "skipped": 0}

    try:
        # Phase 1: users, auths, chats — commit first so messages can reference them
        async with async_session() as db:
            await _migrate_users(cur, db, stats)
            await _migrate_auths(cur, db, stats)
            await _migrate_chats(cur, db, stats)
            await db.commit()

        print(f"[migration] Phase 1 done — users:{stats['users']} chats:{stats['chats']}")

        # Phase 2: messages in a fresh session (avoids identity-map state issues)
        use_table = False
        if "chat_message" in db_tables:
            cur.execute("SELECT COUNT(*) FROM chat_message")
            use_table = (cur.fetchone()[0] or 0) > 0

        print(f"[migration] messages source: {'chat_message table' if use_table else 'chat JSON blob'}")
        async with async_session() as db:
            if use_table:
                await _migrate_messages_from_table(cur, db, stats)
            else:
                await _migrate_messages_from_blob(cur, db, stats)
            await db.commit()
    finally:
        conn.close()

    _write_marker(webui_path, stats)
    print(
        f"[migration] Done — users: {stats['users']}, chats: {stats['chats']}, "
        f"messages: {stats['messages']}, skipped: {stats['skipped']}"
    )


# ---------------------------------------------------------------------------
# Entity migrators
# ---------------------------------------------------------------------------

async def _migrate_users(cur: sqlite3.Cursor, db, stats: dict) -> None:
    cur.execute(
        'SELECT id, name, email, role, profile_image_url, settings, '
        'created_at, updated_at, last_active_at, username FROM "user"'
    )

    seen_usernames: set[str] = set()

    for row in cur.fetchall():
        uid = _uid(row["id"])
        if not uid:
            stats["skipped"] += 1
            continue

        existing = await db.get(User, uid)
        if existing:
            continue

        email = (row["email"] or "").strip().lower()
        if not email:
            stats["skipped"] += 1
            continue

        # Build a unique username
        base = (row["username"] or email.split("@")[0] or "user").strip()
        username = base
        suffix = 1
        while username in seen_usernames:
            username = f"{base}_{suffix}"
            suffix += 1
        seen_usernames.add(username)

        settings = _json_field(row["settings"]) or {}

        user = User(
            id=uid,
            email=email,
            username=username,
            name=(row["name"] or username).strip(),
            role=row["role"] or "user",
            profile_image_url=row["profile_image_url"],
            settings=settings,
            is_active=True,
            created_at=_ts(row["created_at"]),
            updated_at=_ts(row["updated_at"]),
            last_active_at=_ts(row["last_active_at"]) if row["last_active_at"] else None,
        )
        db.add(user)
        stats["users"] += 1

    await db.flush()


async def _migrate_auths(cur: sqlite3.Cursor, db, stats: dict) -> None:
    cur.execute("SELECT id, password FROM auth")

    for row in cur.fetchall():
        uid = _uid(row["id"])
        if not uid:
            continue

        existing = await db.get(Auth, uid)
        if existing:
            continue

        user = await db.get(User, uid)
        if not user:
            continue  # user wasn't migrated (bad id etc.)

        password_hash = row["password"] or ""
        if not password_hash:
            continue

        auth = Auth(id=uid, password_hash=password_hash)
        db.add(auth)
        stats["auths"] += 1

    await db.flush()


async def _migrate_chats(cur: sqlite3.Cursor, db, stats: dict) -> None:
    cur.execute(
        "SELECT id, user_id, title, share_id, archived, pinned, meta, created_at, updated_at "
        "FROM chat"
    )

    for row in cur.fetchall():
        cid = _uid(row["id"])
        uid = _uid(row["user_id"])
        if not cid or not uid:
            stats["skipped"] += 1
            continue

        existing = await db.get(Chat, cid)
        if existing:
            continue

        user = await db.get(User, uid)
        if not user:
            stats["skipped"] += 1
            continue

        chat = Chat(
            id=cid,
            user_id=uid,
            title=(row["title"] or "Imported Chat")[:500],
            pinned=bool(row["pinned"]),
            archived=bool(row["archived"]),
            share_id=row["share_id"] or None,
            meta=_json_field(row["meta"]) or {},
            created_at=_ts(row["created_at"]),
            updated_at=_ts(row["updated_at"]),
        )
        db.add(chat)
        stats["chats"] += 1

    await db.flush()


async def _migrate_messages_from_table(cur: sqlite3.Cursor, db, stats: dict) -> None:
    """Newer open-webui: normalized chat_message table."""
    from sqlalchemy import select

    # Pre-load all migrated chat IDs — avoids identity-map UUID lookup issues
    result = await db.execute(select(Chat.id))
    valid_chat_ids: set[uuid.UUID] = {row[0] for row in result.fetchall()}

    # chat.model cache: chat_id -> Chat object for backfill
    chat_cache: dict[uuid.UUID, Chat] = {}

    cur.execute(
        "SELECT id, chat_id, parent_id, role, content, output, model_id, usage, created_at "
        "FROM chat_message ORDER BY created_at ASC"
    )

    rows = cur.fetchall()

    for row in rows:
        try:
            # open-webui stores id as "{chat_uuid}-{message_uuid}" — take last 36 chars
            raw_id = str(row["id"] or "")
            mid = _uid(raw_id[-36:]) if len(raw_id) >= 36 else _uid(raw_id)
            if not mid:
                mid = uuid.uuid4()  # fallback: generate new

            cid = _uid(row["chat_id"])
            if not cid or cid not in valid_chat_ids:
                continue

            role = row["role"] or "user"
            if role not in ("user", "assistant", "system", "tool"):
                continue

            raw_content = row["content"] or row["output"] or ""
            content = _decode_content(raw_content)
            if not content:
                continue

            model = row["model_id"] or None
            token_count = None
            usage = _json_field(row["usage"])
            if isinstance(usage, dict):
                pt = usage.get("prompt_tokens") or 0
                ct = usage.get("completion_tokens") or 0
                token_count = (pt + ct) or None

            # Backfill model on chat from first assistant message
            if model and role == "assistant":
                if cid not in chat_cache:
                    chat_obj = await db.get(Chat, cid)
                    if chat_obj:
                        chat_cache[cid] = chat_obj
                chat_obj = chat_cache.get(cid)
                if chat_obj and not chat_obj.model:
                    chat_obj.model = model

            msg = Message(
                id=mid,
                chat_id=cid,
                parent_id=_uid(row["parent_id"]) if row["parent_id"] else None,
                role=role,
                content=content,
                model=model,
                token_count=token_count,
                created_at=_ts(row["created_at"]),
            )
            db.add(msg)
            stats["messages"] += 1
        except Exception:
            stats["skipped"] += 1
    await db.flush()


async def _migrate_messages_from_blob(cur: sqlite3.Cursor, db, stats: dict) -> None:
    """Legacy open-webui: messages embedded in chat.chat JSON blob."""
    from sqlalchemy import func, select
    cur.execute("SELECT id, chat FROM chat WHERE chat IS NOT NULL AND chat != ''")

    rows = cur.fetchall()

    for row in rows:
        cid = _uid(row["id"])
        if not cid:
            continue

        chat = await db.get(Chat, cid)
        if not chat:
            continue

        # Skip if messages already exist for this chat (idempotency guard)
        count_result = await db.execute(
            select(func.count()).select_from(Message).where(Message.chat_id == cid)
        )
        if count_result.scalar_one() > 0:
            continue

        try:
            blob = _json_field(row["chat"])
            if not blob:
                continue

            # Try history.messages (dict keyed by id) first, then messages list
            history = blob.get("history", {})
            raw_msgs = history.get("messages", {})
            if isinstance(raw_msgs, dict):
                msg_list = sorted(
                    raw_msgs.values(),
                    key=lambda m: m.get("timestamp", 0) if isinstance(m, dict) else 0,
                )
            elif isinstance(raw_msgs, list):
                msg_list = raw_msgs
            else:
                msg_list = blob.get("messages", [])

            for msg_data in msg_list:
                if not isinstance(msg_data, dict):
                    continue

                role = msg_data.get("role", "user")
                if role not in ("user", "assistant", "system"):
                    continue

                content = _decode_content(msg_data.get("content", ""))
                if not content:
                    continue

                model = msg_data.get("model") or None
                if not chat.model and model and role == "assistant":
                    chat.model = model

                msg = Message(
                    chat_id=cid,
                    role=role,
                    content=content,
                    model=model,
                    created_at=_ts(msg_data.get("timestamp")),
                )
                db.add(msg)
                stats["messages"] += 1

        except Exception:
            stats["skipped"] += 1
            continue

    await db.flush()
