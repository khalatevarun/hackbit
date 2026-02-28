from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()


def send_message(chat_id: str, text: str, links: list[dict] | None = None) -> bool:
    """Send a Telegram message. Returns True on success."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return False

    # Build full text with optional links appended
    full_text = text
    if links:
        full_text += "\n\n*Helpful resources:*"
        for link in links[:3]:
            title = link.get("title", "Link")
            url = link.get("url", "")
            if url:
                full_text += f"\n• [{title}]({url})"

    payload = {
        "chat_id": chat_id,
        "text": full_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def parse_webhook_update(body: dict) -> dict | None:
    """Extract {chat_id, text} from a Telegram webhook update. Returns None if not a text message."""
    message = body.get("message") or body.get("edited_message")
    if not message:
        return None
    text = message.get("text", "").strip()
    if not text:
        return None
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return None
    return {"chat_id": chat_id, "text": text}
