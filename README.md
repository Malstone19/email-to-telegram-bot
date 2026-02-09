# Парсинг почты → Telegram-группа

Скрипт забирает письма с корпоративной почты (IMAP) и пересылает их в указанную Telegram-группу. Удобно для перехвата писем с тестовыми SMS-кодами.

## Что нужно

- Python 3.8+
- Корпоративная почта с доступом по IMAP (хост, логин, пароль или пароль приложения)
- Telegram-бот (токен у вас уже есть)
- Группа в Telegram, куда добавлен этот бот

## Установка

```bash
cd bot_codes
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка

1. **Создайте файл `.env`** (скопируйте из `.env.example`):

   ```bash
   cp .env.example .env
   ```

2. **Заполните переменные в `.env`:**

   - `TELEGRAM_BOT_TOKEN` — токен вашего бота (например `8387523753:AAG...`).
   - `TELEGRAM_CHAT_ID` — ID группы (см. ниже).
   - `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD` — данные корпоративной почты.
   - При необходимости укажите `IMAP_FOLDER` (по умолчанию `INBOX`) и `IMAP_PORT` (по умолчанию 993).

3. **Узнать ID группы (chat_id):** создайте группу, добавьте туда бота, напишите в группе любое сообщение. Затем откройте в браузере (подставьте свой токен):
   `https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates` — в ответе найдите `"chat":{"id":-100...}` и подставьте это число в `TELEGRAM_CHAT_ID`.

## Запуск

Проверка почты раз в 60 секунд (интервал можно задать в `.env` как `CHECK_INTERVAL_SEC`):

```bash
python email_to_telegram.py
```

Для постоянной работы можно запустить в фоне или через systemd/supervisor.

## Запуск в Docker

### Быстрый старт с docker-compose

1. Убедитесь, что файл `.env` настроен (см. раздел "Настройка" выше).

2. Запустите контейнер:
   ```bash
   docker-compose up -d
   ```

3. Просмотр логов:
   ```bash
   docker-compose logs -f
   ```

4. Остановка:
   ```bash
   docker-compose down
   ```

### Сборка и запуск без docker-compose

1. Соберите образ:
   ```bash
   docker build -t email-to-telegram-bot .
   ```

2. Запустите контейнер:
   ```bash
   docker run -d \
     --name email-to-telegram-bot \
     --restart unless-stopped \
     --env-file .env \
     email-to-telegram-bot
   ```

3. Просмотр логов:
   ```bash
   docker logs -f email-to-telegram-bot
   ```

4. Остановка:
   ```bash
   docker stop email-to-telegram-bot
   docker rm email-to-telegram-bot
   ```

### Развертывание на сервере

Подробная инструкция по развертыванию на стороннем сервере находится в файле [DEPLOY.md](DEPLOY.md).

Краткая версия:

1. Скопируйте проект на сервер (например, через `scp` или `git clone`).

2. На сервере создайте файл `.env` с необходимыми переменными.

3. Установите Docker (если не установлен):
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose
   sudo usermod -aG docker $USER
   ```

4. Запустите через docker-compose:
   ```bash
   docker-compose up -d --build
   ```

5. Для автоматического запуска при перезагрузке сервера Docker уже настроен через `restart: unless-stopped` в docker-compose.yml.

## Формат сообщений в Telegram

Для каждого нового письма в группу уходит:

- тема, отправитель, дата;
- автоматически найденные коды в тексте (например «код: 123456», 6-значные числа);
- краткий превью тела письма.

После успешной отправки письмо помечается как прочитанное, чтобы не пересылать его повторно.

## Безопасность

- Токен бота и пароль почты храните только в `.env`; файл `.env` не попадает в git (см. `.gitignore`).
- Не публикуйте `.env` и не коммитьте в репозиторий реальные токены и пароли.
