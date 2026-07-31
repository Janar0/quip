from datetime import UTC, datetime, timedelta

from quip.models.user import TelegramLinkToken, User
from quip.services.telegram_auth import _token_hash, claim_telegram_link


async def test_claim_rehomes_legacy_telegram_user(db_session):
    legacy = User(
        email="telegram-123@local.quip",
        username="telegram_123",
        name="Telegram",
        role="user",
        telegram_user_id="123",
    )
    user = User(
        email="real@quip.dev",
        username="real",
        name="Real User",
        role="user",
    )
    raw_token = "link_legacy_claim"
    db_session.add_all(
        [
            legacy,
            user,
            TelegramLinkToken(
                user_id=None,
                telegram_user_id="123",
                token_hash=_token_hash(raw_token),
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            ),
        ]
    )
    await db_session.commit()

    await claim_telegram_link(db_session, raw_token, user)

    assert user.telegram_user_id == "123"
    assert legacy.telegram_user_id is None
