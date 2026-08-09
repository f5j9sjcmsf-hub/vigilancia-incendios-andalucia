import requests
import html

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text):
    """
    Envía un mensaje a Telegram utilizando HTML.

    Se utiliza HTML porque permite controlar de forma sencilla:
    - <b>negrita</b>
    - <i>cursiva</i>
    """

    response = requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()
