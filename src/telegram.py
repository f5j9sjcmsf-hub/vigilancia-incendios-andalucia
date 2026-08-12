import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _telegram_call(method, payload):
    response = requests.post(
        f"{API}/{method}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def remove_commands():
    """
    Elimina los comandos registrados del bot para que el chat no ofrezca
    un menú de comandos.

    No lee mensajes de usuarios y no crea ningún botón.
    """
    if not TELEGRAM_BOT_TOKEN:
        return None

    try:
        return _telegram_call(
            "deleteMyCommands",
            {},
        )
    except Exception as exc:
        print(f"[TELEGRAM] deleteMyCommands: {type(exc).__name__}: {exc}")
        return None


def send_message(text):
    """
    Envía únicamente mensajes de salida.

    v35:
    - No usa botones inline.
    - No usa ReplyKeyboardMarkup.
    - No procesa comandos.
    - Envía remove_keyboard=True para retirar del chat cualquier teclado
      persistente que hubiera dejado una versión anterior.
    - Desactiva la previsualización de enlaces.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")

    # Elimina el menú de comandos si existía de versiones anteriores.
    remove_commands()

    response = requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "remove_keyboard": True
            },
        },
        timeout=30,
    )

    response.raise_for_status()
    return response.json()
