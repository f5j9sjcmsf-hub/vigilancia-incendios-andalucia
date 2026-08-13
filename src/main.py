from copy import deepcopy
from datetime import datetime

from config import TIMEZONE
from logic import (
    format_snapshot,
    initialize_baseline,
    process_incidents,
    process_reopenings,
)
from sources import fetch_official_incidents, fetch_official_reopenings
from storage import load_state, save_state
from telegram import send_message


def _send_telegram(text, label):
    """Envía un aviso y falla la ejecución si Telegram no lo confirma."""
    result = send_message(text)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(
            f"Telegram no confirmó el envío de {label}: {result!r}"
        )
    print(f"[TELEGRAM] {label}: enviado correctamente.")


def _snapshot_due(state, now, minimum_minutes=55):
    """Limita el resumen periódico aunque la vigilancia sea más frecuente."""
    previous = state.get("last_snapshot_at")
    if not previous:
        return True
    try:
        previous_at = datetime.fromisoformat(str(previous).replace("Z", "+00:00"))
    except ValueError:
        return True
    if previous_at.tzinfo is None:
        previous_at = previous_at.replace(tzinfo=TIMEZONE)
    return (now - previous_at).total_seconds() >= minimum_minutes * 60


def main():
    """
    Vigilancia de todos los cortes por incendio publicados por INFOCAR/DGT
    en Andalucía. INFOCA solo enriquece internamente la identificación del
    incendio; los mensajes no muestran noticias, titulares ni enlaces.

    El estado se guarda de forma transaccional: si cualquier mensaje falla,
    GitHub Actions termina con error y la siguiente ejecución lo reintentará.
    """
    print("=" * 60)
    print("VIGILANCIA DE INCENDIOS EN ANDALUCÍA v40")
    print("=" * 60)

    state = load_state()
    if not isinstance(state, dict):
        state = {}
    working_state = deepcopy(state)

    print("[VIGILANCIA] Consultando INFOCAR/DGT para toda Andalucía...")
    detected = fetch_official_incidents()
    captured = datetime.now(TIMEZONE)
    captured_at = captured.isoformat()
    print(f"[VIGILANCIA] Incidentes activos detectados: {len(detected)}")

    working_state.setdefault(
        "monitoring_initialized",
        bool(working_state.get("incidents")),
    )

    if not working_state.get("monitoring_initialized"):
        _send_telegram(
            format_snapshot(detected, captured_at),
            "actualización de estado",
        )
        initialize_baseline(working_state, detected)
        working_state["baseline_at"] = captured_at
        working_state["last_run"] = captured_at
        working_state["last_snapshot_at"] = captured_at
        save_state(working_state)
        print("[VIGILANCIA] Línea base creada sin avisos retrospectivos.")
        print("=" * 60)
        return

    reopenings = fetch_official_reopenings(working_state, detected)
    reopening_messages = process_reopenings(working_state, reopenings)
    print(f"[VIGILANCIA] Reaperturas nuevas: {len(reopening_messages)}")
    for message in reopening_messages:
        _send_telegram(message, "aviso de reapertura")

    incident_messages = process_incidents(working_state, detected)
    print(f"[VIGILANCIA] Cortes nuevos o ampliados: {len(incident_messages)}")
    for message in incident_messages:
        _send_telegram(message, "aviso de corte")

    if _snapshot_due(state, captured):
        _send_telegram(
            format_snapshot(detected, captured_at),
            "actualización de estado",
        )
        working_state["last_snapshot_at"] = captured_at

    working_state["monitoring_initialized"] = True
    working_state["last_run"] = captured_at
    save_state(working_state)

    print("[VIGILANCIA] Estado guardado correctamente.")
    print("=" * 60)


if __name__ == "__main__":
    main()
