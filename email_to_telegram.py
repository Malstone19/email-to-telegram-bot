#!/usr/bin/env python3
"""
Парсинг писем с корпоративной почты и отправка в Telegram-группу.
Подходит для пересылки писем с тестовыми SMS-кодами.
"""

import os
import re
import ssl
import time
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime

import requests
from dotenv import load_dotenv

# Убрать предупреждение при verify=False (корпоративный прокси/SSL)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# .env из папки скрипта, чтобы работало при любом текущем каталоге
_script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_script_dir, ".env"))
load_dotenv()

# Конфиг из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", "143"))
IMAP_USE_SSL = os.getenv("IMAP_USE_SSL", "0").strip().lower() in ("1", "true", "yes")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")
IMAP_TIMEOUT = int(os.getenv("IMAP_TIMEOUT", "30"))
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "60"))
# В корпоративных сетях с перехватом SSL: SKIP_SSL_VERIFY=1
VERIFY_SSL = os.getenv("SKIP_SSL_VERIFY", "").strip() != "1"


def decode_mime_header(s):
    """Декодирует заголовок письма (тема, от кого)."""
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def get_body(msg):
    """Извлекает текстовое тело письма."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = (payload or b"").decode(charset, errors="replace")
                    break
                except Exception:
                    pass
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        raw = (payload or b"").decode(charset, errors="replace")
                        # Убираем теги для краткости
                        body = re.sub(r"<[^>]+>", " ", raw).strip()
                        body = re.sub(r"\s+", " ", body)[:2000]
                        break
                    except Exception:
                        pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body = (payload or b"").decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload() or "")[:2000]
    return (body or "").strip()[:3000]


def extract_codes(text):
    """Ищет в тексте типичные коды (цифры 4–8 символов, коды типа 'код: 123456')."""
    codes = []
    # Паттерны: "код: 123456", "code: 123456", "пароль: 1234", только цифры 4-8 подряд
    for pattern in [
        r"(?:код|code|пароль|password|pin)[:\s]*(\d{4,8})",
        r"\b(\d{6})\b",  # типичный 6-значный SMS
        r"\b(\d{4,8})\b",
    ]:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            codes.append(m.group(1))
    return list(dict.fromkeys(codes))  # без дубликатов


def send_telegram(text: str, debug=False):
    """Отправляет сообщение в Telegram-группу. Возвращает (ok, response_data)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    if len(text) > 4000:
        text = text[:3997] + "..."
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10, verify=VERIFY_SSL)
        data = r.json()
        if not data.get("ok"):
            print("Telegram API error:", data.get("description", data))
            return False, data
        if debug:
            result = data.get("result", {})
            chat = result.get("chat", {})
            print("Telegram ответ: чат id =", chat.get("id"), ", название =", chat.get("title", chat.get("first_name", "?")))
        return True, data
    except requests.exceptions.SSLError as e:
        print("Telegram SSL error (добавьте в .env: SKIP_SSL_VERIFY=1):", e)
        return False, None
    except Exception as e:
        print("Telegram request error:", e)
        return False, None


def format_email_message(msg) -> str:
    """Форматирует письмо для отправки в Telegram."""
    subject = decode_mime_header(msg.get("Subject"))
    from_ = decode_mime_header(msg.get("From"))
    date_raw = msg.get("Date")
    date_str = ""
    if date_raw:
        try:
            dt = parsedate_to_datetime(date_raw)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = date_raw

    body = get_body(msg)
    codes = extract_codes(subject + " " + body)

    lines = [
        "📧 Новое письмо",
        f"Тема: {subject or '(без темы)'}",
        f"От: {from_ or '(неизвестно)'}",
        f"Дата: {date_str}",
    ]
    if codes:
        lines.append(f"Коды: {', '.join(codes)}")
    if body:
        # Ограничиваем превью тела
        preview = body.replace("\n", " ").strip()[:500]
        if len(body) > 500:
            preview += "..."
        lines.append(f"\n{preview}")

    return "\n".join(lines)


def fetch_and_forward():
    """Проверяет почту и пересылает новые письма в Telegram."""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, IMAP_HOST, IMAP_USER, IMAP_PASSWORD]):
        print("Заполните TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, IMAP_* в .env")
        return

    try:
        if IMAP_USE_SSL:
            if VERIFY_SSL:
                mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT)
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=IMAP_TIMEOUT)
        else:
            mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select(IMAP_FOLDER)
    except Exception as e:
        print("IMAP error:", e)
        return

    try:
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            print("IMAP search error:", status)
            return
        ids = data[0].split() if data and data[0] else []
        if not ids:
            print("Проверка почты: новых (непрочитанных) писем нет")
            return

        print(f"Проверка почты: найдено непрочитанных писем: {len(ids)}")
        for eid in ids:
            try:
                status, data = mail.fetch(eid, "(RFC822)")
                if status != "OK" or not data:
                    continue
                raw = data[0][1]
                msg = email.message_from_bytes(raw)
                text = format_email_message(msg)
                ok, _ = send_telegram(text)
                if ok:
                    mail.store(eid, "+FLAGS", "\\Seen")
                    print("  → отправлено в Telegram")
                else:
                    print("  → ошибка отправки в Telegram")
            except Exception as e:
                print("Error processing email:", e)
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def test_imap_connection():
    """Проверяет доступ к почте при запуске."""
    if not all([IMAP_HOST, IMAP_USER, IMAP_PASSWORD]):
        print("Почта: не настроена (IMAP_HOST, IMAP_USER, IMAP_PASSWORD в .env)")
        return
    try:
        if IMAP_USE_SSL:
            if VERIFY_SSL:
                mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT)
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=IMAP_TIMEOUT)
        else:
            mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        status, _ = mail.select(IMAP_FOLDER)
        if status != "OK":
            print("Почта: папка", IMAP_FOLDER, "не найдена или недоступна")
            mail.logout()
            return
        # количество писем в папке
        status, data = mail.search(None, "ALL")
        total = len(data[0].split()) if data and data[0] else 0
        status_unseen, data_unseen = mail.search(None, "UNSEEN")
        unseen = len(data_unseen[0].split()) if data_unseen and data_unseen[0] else 0
        mail.logout()
        print("Почта: подключение OK, папка", IMAP_FOLDER, "— всего писем:", total, ", непрочитанных:", unseen)
    except Exception as e:
        print("Почта: ошибка подключения —", e)


def main():
    print("Email → Telegram: запуск. Интервал проверки:", CHECK_INTERVAL_SEC, "сек")
    print("SSL проверка при запросах:", "выкл" if not VERIFY_SSL else "вкл")
    test_imap_connection()
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        ok, data = send_telegram("🔔 Бот запущен, ожидаю новые письма с почты.", debug=True)
        if ok:
            chat = (data or {}).get("result", {}).get("chat", {})
            name = chat.get("title") or chat.get("first_name") or "?"
            print("Тест: сообщение отправлено в чат:", name, "(id:", chat.get("id"), ")")
        else:
            print("Тест: не удалось отправить в группу — проверьте TELEGRAM_CHAT_ID и токен.")
    while True:
        fetch_and_forward()
        time.sleep(CHECK_INTERVAL_SEC)
        print()  # разделитель между циклами


if __name__ == "__main__":
    main()
