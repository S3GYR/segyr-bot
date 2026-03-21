from __future__ import annotations

import smtplib
import ssl
from email.mime.text import MIMEText
from typing import Any
from urllib import parse, request

from config.settings import settings


def send_email(to: str, subject: str, message: str) -> bool:
    host = settings.smtp_host
    port = settings.smtp_port
    user = settings.smtp_user
    password = settings.smtp_password
    if not host or not port or not user or not password:
        return False
    mime_msg = MIMEText(message, _charset="utf-8")
    mime_msg["Subject"] = subject
    mime_msg["From"] = user
    mime_msg["To"] = to
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(mime_msg)
        return True
    except Exception:
        return False


def send_telegram(chat_id: str, message: str) -> bool:
    token = settings.telegram_bot_token
    if not token or not chat_id:
        return False
    base_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    data = parse.urlencode(payload).encode()
    try:
        req = request.Request(base_url, data=data)
        with request.urlopen(req, timeout=10):
            pass
        return True
    except Exception:
        return False


def send_notification(notif_type: str, message: str, entreprise_id: str | None = None, meta: dict[str, Any] | None = None) -> bool:
    """Dispatch notification by type. Returns True if dispatched without error."""
    meta = meta or {}
    if notif_type == "finance":
        to = meta.get("email") or settings.smtp_user
        subject = meta.get("subject") or "Alerte finance SEGYR-BOT"
        return bool(to) and send_email(to, subject, message)
    if notif_type == "chantier":
        chat_id = meta.get("chat_id") or settings.telegram_chat_id if hasattr(settings, "telegram_chat_id") else None
        return bool(chat_id) and send_telegram(chat_id, message)
    return False
