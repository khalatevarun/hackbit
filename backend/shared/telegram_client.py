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


def send_message_with_buttons(
    chat_id: str,
    text: str,
    buttons: list[list[dict]],
) -> bool:
    """Send a Telegram message with an inline keyboard.
    buttons: list of rows, each row is a list of {text, callback_data}.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": buttons},
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


def answer_callback_query(callback_query_id: str, text: str = "") -> bool:
    """Acknowledge a callback query (removes the loading spinner on the button)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def parse_webhook_update(body: dict) -> dict | None:
    """Extract update info from a Telegram webhook payload.

    Returns one of:
    - {"type": "message", "chat_id": str, "text": str}   for text messages
    - {"type": "callback", "chat_id": str, "data": str, "callback_query_id": str}  for button presses
    - None for unsupported updates
    """
    # Callback query (inline button press)
    cq = body.get("callback_query")
    if cq:
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        data = cq.get("data", "")
        cq_id = cq.get("id", "")
        if chat_id and data:
            return {"type": "callback", "chat_id": chat_id, "data": data, "callback_query_id": cq_id}
        return None

    # Regular text message
    message = body.get("message") or body.get("edited_message")
    if not message:
        return None
    text = message.get("text", "").strip()
    if not text:
        return None
    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return None
    return {"type": "message", "chat_id": chat_id, "text": text}
