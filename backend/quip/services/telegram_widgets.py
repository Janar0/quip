"""Readable Telegram fallbacks for QUIP's WebUI-only HTML widgets."""

from __future__ import annotations

import json
from typing import Any

_WIDGET_LABELS = {
    "weather": "Погода",
    "sports": "Спорт",
    "poll": "Опрос",
    "places": "Место",
    "converter": "Конвертация",
    "recipe": "Рецепт",
}
_WIDGET_ICONS = {
    "weather": "🌤",
    "sports": "🏆",
    "poll": "📊",
    "places": "📍",
    "converter": "🔄",
    "recipe": "🍽",
}


def _value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def widget_to_markdown(name: str, data: dict[str, Any]) -> str:
    """Turn a widget result into a compact, readable Telegram message.

    Telegram cannot execute the WebUI widget's sandboxed HTML/JavaScript. The
    data itself is still useful, so every widget gets a native-text fallback.
    Unknown/admin-created widgets use a conservative JSON representation.
    """
    title = _WIDGET_LABELS.get(name, name.replace("_", " ").title())
    lines = [f"{_WIDGET_ICONS.get(name, '🧩')} **{title}**"]

    if data.get("error"):
        return f"{lines[0]}\n\n{data['error']}"

    if name == "weather":
        city = _value(data.get("city"))
        lines.append(f"**{city}** — {_value(data.get('condition'))} {_value(data.get('icon_emoji'))}")
        lines.extend(
            [
                f"Температура: **{_value(data.get('temp'))}°C** (ощущается как {_value(data.get('feels_like'))}°C)",
                f"Влажность: {_value(data.get('humidity'))}% · ветер: {_value(data.get('wind_speed'))} м/с {_value(data.get('wind_dir'))}",
                f"Давление: {_value(data.get('pressure'))} мм рт. ст.",
            ]
        )
        forecast = data.get("forecast") or []
        if forecast:
            lines.append("\n**Прогноз:**")
            lines.extend(
                f"• {_value(item.get('day'))} {_value(item.get('icon_emoji'))}: {_value(item.get('temp_min'))}…{_value(item.get('temp_max'))}°C — {_value(item.get('condition'))}"
                for item in forecast
                if isinstance(item, dict)
            )
        return "\n".join(lines)

    if name == "sports":
        if data.get("league"):
            lines.append(f"**{data['league']}**")
        if data.get("home") and data.get("away"):
            home, away = data["home"], data["away"]
            lines.append(
                f"{_value(home.get('name'))} **{_value(home.get('score'))} — {_value(away.get('score'))}** {_value(away.get('name'))}"
            )
            if data.get("status"):
                lines.append(f"Статус: {_value(data['status'])}")
            lines.extend(f"• {_value(event)}" for event in data.get("events") or [])
        for team in data.get("teams") or []:
            if isinstance(team, dict):
                lines.append(
                    f"{_value(team.get('pos'))}. **{_value(team.get('name'))}** — {_value(team.get('points'))} очк. ({_value(team.get('played'))} игр.)"
                )
        return "\n".join(lines)

    if name == "poll":
        if data.get("question"):
            lines.append(f"**{data['question']}**")
        for option in data.get("options") or []:
            if isinstance(option, dict):
                detail = f" — {option['description']}" if option.get("description") else ""
                lines.append(f"• **{_value(option.get('label'))}**: {_value(option.get('percent'))}%{detail}")
        if data.get("total_votes") is not None:
            lines.append(f"Всего голосов: {_value(data.get('total_votes'))}")
        return "\n".join(lines)

    if name == "places":
        if data.get("name"):
            lines.append(f"**{data['name']}**")
        for label, key in (("Адрес", "address"), ("Категория", "category"), ("Рейтинг", "rating"), ("Часы", "hours"), ("Телефон", "phone")):
            if data.get(key):
                lines.append(f"{label}: {_value(data[key])}")
        if data.get("description"):
            lines.append(str(data["description"]))
        if data.get("website"):
            lines.append(f"[Сайт]({data['website']})")
        if data.get("lat") is not None and data.get("lon") is not None:
            url = f"https://www.openstreetmap.org/?mlat={data['lat']}&mlon={data['lon']}#map=16/{data['lat']}/{data['lon']}"
            lines.append(f"[Открыть на карте]({url})")
        return "\n".join(lines)

    if name == "converter":
        lines.append(
            f"**{_value(data.get('from_value'))} {_value(data.get('from_unit'))}** → **{_value(data.get('to_value'))} {_value(data.get('to_unit'))}**"
        )
        if data.get("from_label") or data.get("to_label"):
            lines.append(f"{_value(data.get('from_label'))} → {_value(data.get('to_label'))}")
        if data.get("formula"):
            lines.append(f"Формула: `{data['formula']}`")
        return "\n".join(lines)

    if name == "recipe":
        if data.get("title"):
            lines.append(f"**{data['title']}**")
        if data.get("description"):
            lines.append(str(data["description"]))
        meta = [f"порций: {data['servings']}" for _ in [0] if data.get("servings")]
        meta.extend(f"время: {data['cook_time']}" for _ in [0] if data.get("cook_time"))
        if meta:
            lines.append(" · ".join(meta))
        ingredients = data.get("ingredients") or []
        if ingredients:
            lines.append("\n**Ингредиенты:**")
            lines.extend(
                f"• {_value(item.get('amount'))} {_value(item.get('unit'))} — {_value(item.get('name'))}"
                for item in ingredients
                if isinstance(item, dict)
            )
        steps = data.get("steps") or []
        if steps:
            lines.append("\n**Шаги:**")
            lines.extend(f"{index}. {_value(step)}" for index, step in enumerate(steps, 1))
        if data.get("notes"):
            lines.append(f"\n**Заметки:**\n{data['notes']}")
        return "\n".join(lines)

    visible = {key: value for key, value in data.items() if key not in {"widget", "template"}}
    return f"{lines[0]}\n```json\n{json.dumps(visible, ensure_ascii=False, indent=2, default=str)}\n```"
