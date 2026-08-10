import os
from datetime import datetime

import requests

from config import TIMEZONE
from storage import load_state, save_state
from sources import (
    fetch_official_incidents,
    fetch_official_reopenings,
)
from logic import (
    initialize_baseline,
    process_incidents,
    process_reopenings,
    format_status,
)
from telegram import send_message


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_API = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if TELEGRAM_BOT_TOKEN
    else ""
)

COMMANDS = {
    "▶️ Iniciar vigilancia": "iniciar",
    "/iniciar": "iniciar",
    "🔄 Reiniciar desde 0": "reiniciar",
    "/reiniciar": "reiniciar",
    "📊 Estado": "estado",
    "/estado": "estado",
    "⏹️ Pausar vigilancia": "pausar",
    "/pausar": "pausar",
}


# ============================================================
# TELEGRAM - CONTROL DEL BOT
# ============================================================


def _telegram_request(method, payload=None):
    if not TELEGRAM_API:
        return None

    try:
        response = requests.post(
            f"{TELEGRAM_API}/{method}",
            json=payload or {},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return None
        return data
    except Exception:
        return None


def _send_control_message(text):
    if not TELEGRAM_API or not TELEGRAM_CHAT_ID:
        return

    keyboard = {
        "keyboard": [
            ["▶️ Iniciar vigilancia", "🔄 Reiniciar desde 0"],
            ["📊 Estado", "⏹️ Pausar vigilancia"],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }

    _telegram_request(
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        },
    )


def _authorized_chat(chat_id):
    return bool(
        TELEGRAM_CHAT_ID
        and str(chat_id) == str(TELEGRAM_CHAT_ID)
    )


def _poll_commands(state):
    """
    Lee las órdenes pendientes del chat configurado.

    GitHub Actions ejecuta este código cada 30 minutos, por lo que una
    pulsación del botón se procesa en la siguiente ejecución del workflow
    (o inmediatamente si se fuerza manualmente el workflow).
    """
    if not TELEGRAM_API or not TELEGRAM_CHAT_ID:
        return None

    offset = state.get("telegram_update_offset")
    payload = {
        "allowed_updates": ["message"],
        "timeout": 1,
    }

    if isinstance(offset, int):
        payload["offset"] = offset

    data = _telegram_request("getUpdates", payload)
    if not data:
        return None

    updates = data.get("result", [])
    if not updates:
        return None

    command = None

    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            state["telegram_update_offset"] = update_id + 1

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if not _authorized_chat(chat.get("id")):
            continue

        text = str(message.get("text") or "").strip()
        normalized = text.lower()

        for label, value in COMMANDS.items():
            if normalized == label.lower():
                command = value
                break

        if command:
            # Si llegan varias órdenes en una ejecución, procesamos la última.
            continue

    return command


# ============================================================
# CONTROL DE ESTADO
# ============================================================


def _activate_from_zero(state, detected):
    """
    Reinicia la memoria de vigilancia y toma la consulta actual como
    fotografía inicial.

    Las carreteras que ya estén cortadas en esta fotografía NO generan aviso.
    Los cambios posteriores sí.
    """
    initialize_baseline(state, detected)
    state["monitoring_active"] = True
    state["monitoring_initialized"] = True
    state["last_run"] = datetime.now(TIMEZONE).isoformat()


def _handle_command(state, command):
    if command == "pausar":
        state["monitoring_active"] = False
        _send_control_message(
            "⏸️ <b>Vigilancia pausada</b>\n\n"
            "No se generarán avisos de cambios mientras esté pausada."
        )
        return True

    if command == "estado":
        _send_control_message(format_status(state))
        return False

    if command in ("iniciar", "reiniciar"):
        detected = fetch_official_incidents()
        _activate_from_zero(state, detected)

        if command == "reiniciar":
            title = "🔄 <b>Bot reiniciado desde 0</b>"
        else:
            title = "▶️ <b>Vigilancia iniciada</b>"

        _send_control_message(
            f"{title}\n\n"
            "Se ha realizado una primera búsqueda en INFOCAR/INFOCA.\n"
            "Las carreteras que ya estaban cortadas quedan registradas "
            "como estado inicial y <b>no generan aviso</b>.\n\n"
            "A partir de la próxima comprobación se avisará de nuevos "
            "cortes y cambios de estado."
        )
        return True

    return False


# ============================================================
# VIGILANCIA NORMAL
# ============================================================


def main():
    state = load_state()

    if not isinstance(state, dict):
        state = {}

    state.setdefault("monitoring_active", True)
    state.setdefault("monitoring_initialized", bool(state.get("incidents")))

    command = _poll_commands(state)

    # Las órdenes de control tienen prioridad sobre la vigilancia normal.
    if command:
        handled = _handle_command(state, command)
        if handled:
            save_state(state)
            return

        # /estado no modifica la fotografía. Continuamos con la vigilancia
        # normal si estaba activa.

    if not state.get("monitoring_active", True):
        state["last_run"] = datetime.now(TIMEZONE).isoformat()
        save_state(state)
        return

    # Primera ejecución de un estado vacío: se toma como línea base.
    # Esto evita que al activar el sistema por primera vez se conviertan
    # los cortes ya existentes en falsos "nuevos cortes".
    if not state.get("monitoring_initialized"):
        detected = fetch_official_incidents()
        _activate_from_zero(state, detected)
        save_state(state)
        return

    # Una única fotografía actual de INFOCAR/DGT + INFOCA.
    detected = fetch_official_incidents()

    # La reapertura se calcula contra el estado anterior, antes de que
    # process_incidents sustituya la fotografía almacenada.
    reopenings = fetch_official_reopenings(
        state,
        detected,
    )

    # Primero notificamos reaperturas.
    for message in process_reopenings(
        state,
        reopenings,
    ):
        send_message(message)

    # Después actualizamos la fotografía actual y notificamos nuevos cortes.
    for message in process_incidents(
        state,
        detected,
    ):
        send_message(message)

    state["last_run"] = datetime.now(TIMEZONE).isoformat()
    state["monitoring_initialized"] = True

    save_state(state)


if __name__ == "__main__":
    main()
