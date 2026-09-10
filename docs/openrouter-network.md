# OpenRouter: DNS и сеть

`[Errno -3] Temporary failure in name resolution` означает, что процесс backend не смог разрешить имя сервера (либо HTTP-прокси). Запрос ещё не дошёл до проверки API-ключа.

Из корня проекта:

```bash
python3 scripts/doctor.py
```

Для production Docker проверяйте **внутри контейнера приложения**:

```bash
docker compose exec -T app python - < scripts/doctor.py
```

Для development Compose:

```bash
docker compose -f docker-compose.dev.yml exec -T backend python - < scripts/doctor.py
```

Скрипт не отправляет API-ключи, не меняет систему, не печатает значения прокси с возможными паролями. Он проверяет DNS, определяет диапазон VPN fake-IP и выполняет HTTPS-запрос к публичному каталогу моделей.

## Как читать результат

- **DNS FAILED**: проверьте DNS хоста, Docker и VPN. `127.0.0.53` — локальный resolver хоста; нельзя просто прописывать его как DNS в другом контейнере.
- **198.18.x.x / 198.19.x.x**: возможен fake-IP режим VPN. Такой адрес требует маршрутизации через соответствующий VPN; контейнер может иметь DNS, но не иметь нужного маршрута.
- **HTTPS FAILED при работающем DNS**: проверьте доступность прокси, VPN, firewall и доверенные CA. `localhost` в контейнере относится к самому контейнеру, а не к хосту.
- **HTTPS 200**: сеть работает в проверенном окружении. Проверка ключа и доступности конкретной модели — отдельный запрос.

Если среда требует HTTP-прокси, HTTPX использует `HTTPS_PROXY`, `HTTP_PROXY` и `NO_PROXY`. Передайте их именно процессу/контейнеру backend. В `NO_PROXY` должны быть локальные сервисы, например `localhost,127.0.0.1,searxng,executor`. SOCKS требует отдельной зависимости; используйте доступный HTTP endpoint вашего VPN/прокси.

Пример **локального** Compose override (значения берутся из окружения или `.env`):

```yaml
services:
  app:
    environment:
      HTTPS_PROXY: ${HTTPS_PROXY}
      HTTP_PROXY: ${HTTP_PROXY}
      NO_PROXY: ${NO_PROXY:-localhost,127.0.0.1,searxng,executor}
```

Применяйте только подходящий вашей сети адрес прокси. Не подменяйте DNS на случайный публичный resolver: это может сломать split-DNS VPN. QUIP не отключает TLS и не подменяет IP OpenRouter.

## Что изменено в коде

Три попытки подключения с паузами 0.5 и 1 секунду. Уже начавшийся ответ не перезапускается: это предотвращает дубли текста, инструментов и расходов. Прокси из окружения сохраняются. [HTTPX: connection retries](https://www.python-httpx.org/advanced/transports/).

При постоянном сбое сообщение объясняет, что проверять на backend. Настройки остаются доступны при недоступном OpenRouter; временный сбой каталога не затирает последнюю известную копию списка моделей.
