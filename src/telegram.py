import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


MAX_MESSAGE_LENGTH = 4000
API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_commands_checked = False


def _call(method, payload=None):
    response = requests.post(
        f"{API}/{method}",
        json=payload or {},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("ok") is not True:
        raise RuntimeError(f"Telegram rechazó {method}: {result!r}")
    return result


def _delete_commands_once():
    global _commands_checked

    if _commands_checked:
        return

    _commands_checked = True
    try:
        _call("deleteMyCommands", {})
    except Exception as exc:
        print(
            "[TELEGRAM] No se pudieron borrar los comandos antiguos: "
            f"{type(exc).__name__}: {exc}"
        )


def _split_message(text):
    text = str(text)
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks = []
    current = []
    current_length = 0

    for line in text.splitlines(keepends=True):
        if len(line) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                "Una línea del mensaje supera el límite de Telegram."
            )

        if current and current_length + len(line) > MAX_MESSAGE_LENGTH:
            chunks.append("".join(current))
            current = []
            current_length = 0

        current.append(line)
        current_length += len(line)

    if current:
        chunks.append("".join(current))

    return chunks


def send_message(text):
    """Envía mensajes sin botones, noticias, enlaces ni teclados."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID."
        )

    _delete_commands_once()

    results = []
    for chunk in _split_message(text):
        results.append(
            _call(
                "sendMessage",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        )

    return {
        "ok": all(result.get("ok") is True for result in results),
        "result": results,
    }
