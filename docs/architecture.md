# Карта проекта

## Backend

| Каталог | Ответственность |
| --- | --- |
| `quip/routers/` | HTTP: проверка доступа, входные данные, вызов сервисов |
| `quip/services/completion/service.py` | HTTP-жизненный цикл send/regenerate, research, запуск ChatRun и события |
| `quip/services/completion/preparation.py` | Общая подготовка модели, бюджета, истории, RAG и workspace |
| `quip/services/completion/admission.py` | Атомарное принятие новой ветки и привязка вложений |
| `quip/services/completion/results.py`, `attachments.py` | Накопление результата потока, сохранение сообщений, подготовка файлов для sandbox |
| `quip/services/completion/stream.py` | Выбор OpenRouter/Ollama, цикл инструментов, поток событий |
| `quip/services/completion/history.py`, `prompt.py` | История, системный промпт, RAG |
| `quip/services/chat_runs.py` | Управление задачами, подписками, heartbeat и handshake завершения |
| `quip/services/chat_run_store.py` | Долговечное состояние: ownership, CAS, cancellation/steering, runner lease |
| `quip/services/chat_run_snapshot.py`, `chat_run_types.py` | Ограничение размера snapshot, типы и константы протокола |
| `quip/providers/types.py` | Общие типы потока: контент, reasoning, usage, tool calls |
| `quip/providers/http.py` | Повторы подключения, закрытие HTTP-ответа, безопасные сетевые ошибки |
| `quip/providers/openrouter.py`, `ollama.py` | Формат запросов и ответов конкретного провайдера |
| `quip/core/config.py` | Настройки: БД → окружение → значение по умолчанию |
| `quip/core/security.py` | Проверка JWT-секрета и атомарная постоянная инициализация для всех способов запуска |
| `quip/models/`, `schemas/`, `migrations/` | Хранение, API-схемы, миграции |
| `quip/executor_app.py` | Изолированный API управления контейнерами песочницы |
| `tests/` | Регрессионные и интеграционные проверки через ASGI |

Поток: HTTP router → CompletionService → StreamOrchestrator → provider → SSE → сохранение сообщений и статуса ChatRun.

Старые импорты типов из `providers.openrouter` пока совместимы. Новому коду следует импортировать типы из `providers.types`. Аналогично `services/config.py` остаётся адаптером для старых импортов; новые используют `core/config.py`.

`chat_runs.py` сохраняет прежние публичные импорты, а storage-функции сосредоточены в `chat_run_store.py`. Проверка ownership и сравнение `write_sequence` должны оставаться частью каждой согласованной операции с метаданными; не заменяйте CAS независимым чтением и записью. Перед сохранением итогового ответа менеджер подтверждает принятый результат завершения, чтобы поздняя отмена не перезаписала уже принятое состояние.

Повторять генерацию после начала передачи запроса/ответа нельзя без явной политики идемпотентности. Текущие повторы ограничены `ConnectError` и `ConnectTimeout`, до получения ответа. Ошибка каталога или billing metadata не должна ломать настройки либо уже полученный ответ.

## Frontend

| Каталог / файл | Ответственность |
| --- | --- |
| `routes/` | Страницы и связка компонентов |
| `lib/api/client.ts` | Cookie auth, единый refresh, HTTP-обёртка |
| `lib/api/chats.ts` | Загрузка/пагинация, отправка, остановка, повтор, редактирование |
| `lib/api/research-projection.ts` | Проекция research-отчёта с проверкой актуальности и идентичности сообщения |
| `lib/api/research-sync.ts` | Polling research-статуса, загрузка/остановка и согласование с текущим stream-контекстом |
| `lib/api/sse.ts` | Декодирование SSE, UTF-8, CRLF, границы пакетов, освобождение reader |
| `lib/api/chat-stream.ts` | Преобразование событий в состояние сообщений |
| `lib/stores/` | Состояние интерфейса и типы |
| `lib/components/chat/` | Composer, список, сообщение, поиск, инструменты |
| `lib/actions/selectable-html.ts` | Сохранение DOM при выделении текста и копирование кода |
| `lib/utils/markdown.ts` | Безопасный рендер Markdown, формулы, источники |
| `lib/services/voice/session.ts` | Владелец звонка: состояние, готовность, отмена запуска, контекст и очередь событий |
| `lib/services/voice/transport.ts` | WebRTC signaling, ICE и очередь data-channel; закрытие снимает listeners и таймеры |
| `lib/services/voice/provider-protocol.ts`, `provider-tools.ts` | Нормализация событий/usage, настройка провайдера и ответы на tool calls |
| `lib/services/voice/media.ts`, `ringback.ts`, `types.ts` | Подготовка видео, звук ожидания, типы публичного API |
| `lib/styles/theme.css` | Токены тем и семантические цвета Tailwind |
| `lib/styles/base.css` | Базовые стили, прокрутка, выделение |
| `lib/styles/prose.css` | Текст, код, таблицы, подсветка синтаксиса |
| `lib/styles/components.css` | Общие стили компонентов и эффекты |
| `app.css` | Точка сборки CSS и шрифтов |

Используйте `text-foreground`, `text-muted`, `text-subtle`, `bg-canvas`, `bg-panel`, `bg-elevated`, `border-outline`, `bg-action`, `text-on-action`. Новые фиксированные нейтральные цвета в компонентах снова сломают светлую тему.

Composer участвует в flex-layout; не возвращайте абсолютное позиционирование с фиксированным отступом у сообщений. Высота ввода меняется при наборе и вложениях.

`selectableHtml` принимает только результат безопасного Markdown renderer. Он откладывает обновление выделенного блока до снятия выделения, затем показывает накопленный текст. Сетевой поток при этом продолжается. Не передавайте туда необработанный HTML модели или пользователя.

Research polling разрешает stream-контекст заново при каждом обновлении. Ответ на старый запрос не должен перезаписать новое содержимое сообщения или отчёт другой ветки. В voice сохраняйте проверку поколения звонка после каждого `await`, который может пережить завершение или новый запуск: старый transport, контекст или transcript continuation не должны менять новую сессию.

Production build дополнительно проверяет сгенерированный service worker: fallback находится в precache и в статической сборке, API исключён из navigation fallback. Настройку `kit.adapterFallback` согласуйте с `adapter-static`, если меняете имя SPA-страницы.

## Как вносить изменения

1. Изменение протокола SSE: backend producer + `sse.ts`/`chat-stream.ts` + регрессионный тест.
2. Изменение цвета: токены темы, затем обе темы в браузере.
3. Изменение схемы БД: новая миграция; не правьте уже выпущенные ревизии.
4. Изменение сетевого поведения: тестируйте восстановление подключения и обрыв после частичного ответа отдельно.
5. Проверяйте отказоустойчивость: ошибка HTTP, отмена, повторная отправка, медленный ответ при переключении чатов/пространств.

При новых изменениях send/regenerate добавляйте общую политику в `preparation.py`, а накопление данных потока — в `results.py`. Проверяйте оба пути: у них общая подготовка, но разные операции принятия сообщения и ветки.
