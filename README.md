# QUIP

Чат с OpenRouter и Ollama: потоковые ответы, ветки диалогов, рабочие пространства, файлы, артефакты и Telegram.

## Локальный запуск

Нужны Python 3.12+, `uv` и Node.js 22+ (как в CI).

```bash
cp .env.example .env
cd backend
uv sync --frozen --extra dev
cd ../frontend
npm ci
cd ..
python3 start.py
```

Приложение: http://127.0.0.1:5173. API: http://127.0.0.1:8000/docs.
Первый администратор создаётся через регистрацию с `BOOTSTRAP_TOKEN` из `.env` либо с автоматически созданным токеном (`backend/data/.bootstrap_token`).

Для OpenRouter задайте `OPENROUTER_API_KEY` в `.env` или в админке. Для Ollama задайте её URL в админке и выберите модель с префиксом `ollama/`. Ключ OpenRouter для обычных ответов Ollama не нужен; отдельные внешние инструменты могут требовать своих настроек.

`.env` из корня загружается при старте backend; переменные окружения имеют приоритет. Настройки, сохранённые в БД, имеют приоритет над окружением. После изменения `.env` перезапустите backend.

По умолчанию используется SQLite. Для внешнего PostgreSQL укажите `DATABASE_URL`. Устаревший `start.py --pg` удалён: он запускал production Compose, в котором PostgreSQL отсутствует. Локальный запуск не собирает Docker-образы автоматически. Песочница кода требует отдельного Docker executor; конфигурация есть в Compose.

## Проверки

```bash
cd backend
uv run --frozen --extra dev pytest -q
uv run --frozen --extra dev ruff check --select E9,F63,F7,F82 quip tests
cd ../frontend
npm run check
npm test
npm run build
```

Тесты провайдеров используют HTTPX MockTransport; реальные ключи и Docker daemon не нужны.

Перед релизом дождитесь успешного workflow **Quality, Build & Push** в GitHub Actions: кроме этих проверок он запускает `pip-audit`, `npm audit --omit=dev --audit-level=high`, проверку Compose и сборку с публикацией Docker-образов. Успешная локальная сборка frontend не подтверждает прохождение всего CI.

## Навигация по проекту

- [Архитектура и правила правок](docs/architecture.md)
- [Диагностика OpenRouter / DNS / VPN](docs/openrouter-network.md)
- [Результаты аудита и ограничения проверки](docs/audit-2026-09-10.md)

Production Compose использует опубликованные образы из GHCR. Изменения локальных исходников не попадут в этот образ автоматически: используйте локальную сборку или штатный CI релиза.
