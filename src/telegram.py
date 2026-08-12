import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _call(method, payload=None):
    response = requests.post(
        f"{API}/{method}",
        json=payload or {},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _remove_old_keyboard():
    """
    Telegram puede conservar el teclado persistente creado por versiones
    antiguas del bot. Esta llamada lo elimina definitivamente.
    """
    try:
        _call(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "\u200b",
                "reply_markup": {"remove_keyboard": True},
            },
        )
    except Exception as exc:
        print(
            f"[TELEGRAM] No se pudo retirar el teclado antiguo: "
            f"{type(exc).__name__}: {exc}"
        )


def _delete_commands():
    """
    Borra los comandos registrados del bot para que no quede un menú de
    comandos de versiones anteriores.
    """
    try:
        _call("deleteMyCommands", {})
    except Exception as exc:
        print(
            f"[TELEGRAM] No se pudieron borrar los comandos: "
            f"{type(exc).__name__}: {exc}"
        )


def send_message(text):
    """
    Bot exclusivamente de salida:
      - sin botones;
      - sin teclado persistente;
      - sin comandos;
      - sin lectura de mensajes de usuarios.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID."
        )

    # Retiramos cualquier teclado/comandos que una versión anterior dejara
    # persistidos. Se hace antes del mensaje real.
    _delete_commands()
    _remove_old_keyboard()

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
