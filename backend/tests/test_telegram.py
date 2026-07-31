from unittest.mock import patch

from quip.services.telegram import (
    TelegramBotService,
    _allowed_user_ids,
    _normalize_telegram_markdown,
    _split_text,
    markdown_to_markdown_v2,
)
from quip.services.telegram_media import describe_media, media_prompt
from quip.services.telegram_widgets import widget_to_markdown
from quip.services.title import _parse_identity, is_implicit_chat_title


def test_markdown_to_telegram_markdown_v2_preserves_common_formatting():
    converted = markdown_to_markdown_v2(
        "# Заголовок\n\n**важно** и `x + y`\n\n- пункт\n\n[ссылка](https://example.com/a_(b))"
    )

    assert "*Заголовок*" in converted
    assert "*важно*" in converted
    assert "`x + y`" in converted
    assert "• пункт" in converted
    assert "[ссылка](https://example.com/a_\\(b\\))" in converted


def test_markdown_to_telegram_escapes_plain_special_characters():
    converted = markdown_to_markdown_v2("Цена: 10.50 — готово!")

    assert "10\\.50" in converted
    assert "готово\\!" in converted


def test_markdown_to_telegram_preserves_quotes_and_task_lists():
    converted = markdown_to_markdown_v2("> **цитата**\n- [x] готово")

    assert "> *цитата*" in converted
    assert "☑ готово" in converted


def test_markdown_table_falls_back_to_readable_code_block():
    converted = markdown_to_markdown_v2("| A | B |\n|---|---|\n| 1 | 2 |")

    assert chr(96) * 3 in converted
    assert "| A | B |" in converted


def test_telegram_sources_become_links_without_raw_preview_urls():
    normalized = _normalize_telegram_markdown("[1] Погода Mail - https://example.com/weather.")

    assert normalized == "[1] [Погода Mail](https://example.com/weather)"
    assert "https://example.com/weather." not in normalized


def test_telegram_widget_has_readable_native_fallback():
    rendered = widget_to_markdown(
        "weather",
        {"city": "Москва", "temp": 24, "condition": "ясно", "forecast": []},
    )

    assert "Москва" in rendered
    assert "24°C" in rendered


def test_chat_identity_parses_json_and_uses_fallback_emoji():
    title, emoji = _parse_identity('{"title":"Погода в Москве","emoji":"🌤"}', "погода")

    assert title == "Погода в Москве"
    assert emoji == "🌤"


def test_chat_identity_replaces_generic_model_emoji_with_semantic_fallback():
    _, emoji = _parse_identity('{"title":"Equation Solving Fun","emoji":"💬"}', "2x+3=12")

    assert emoji == "🧮"


def test_telegram_default_topic_names_are_implicit():
    assert is_implicit_chat_title("Новый чат")
    assert not is_implicit_chat_title("Моя тема")


def test_split_text_keeps_chunks_under_telegram_limit():
    chunks = _split_text("a " * 3000)

    assert len(chunks) > 1
    assert all(len(chunk) <= 4016 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == "a" * 3000


def test_telegram_commands():
    assert TelegramBotService._command("/search cats") == ("/search", "cats")
    assert TelegramBotService._command("/help@quip_bot") == ("/help", "")
    assert TelegramBotService._command("обычный текст") == (None, "обычный текст")


def test_telegram_allowlist_is_optional_extra_gate():
    with patch("quip.services.telegram.get_setting", return_value="123, 456 789"):
        assert _allowed_user_ids() == {"123", "456", "789"}


def test_telegram_media_selects_largest_photo_and_caption_attachments():
    media = describe_media(
        {
            "message_id": 42,
            "photo": [
                {"file_id": "small", "width": 100, "height": 100, "file_size": 1000},
                {"file_id": "large", "width": 1200, "height": 900, "file_size": 9000},
            ],
        }
    )

    assert media is not None
    assert media.file_id == "large"
    assert media.kind == "image"
    assert media.filename == "telegram-photo-42.jpg"
    assert media_prompt(media) == "Проанализируй прикреплённое изображение."


def test_telegram_media_supports_documents_voice_and_video():
    document = describe_media({"document": {"file_id": "doc", "file_name": "report.pdf", "mime_type": "application/pdf"}})
    voice = describe_media({"voice": {"file_id": "voice", "mime_type": "audio/ogg"}})
    video = describe_media({"video": {"file_id": "video", "file_name": "clip.mp4", "mime_type": "video/mp4"}})

    assert document and document.kind == "document" and document.filename == "report.pdf"
    assert voice and voice.kind == "audio" and voice.filename.endswith(".ogg")
    assert video and video.kind == "video" and video.content_type == "video/mp4"
