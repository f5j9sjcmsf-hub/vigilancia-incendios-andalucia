from datetime import datetime

from config import TIMEZONE
from storage import load_state, save_state
from sources import (
    fetch_official_incidents,
    fetch_official_reopenings,
)
from logic import (
    process_incidents,
    process_reopenings,
    initialize_baseline,
    format_snapshot,
)
from telegram import send_message


def _send_telegram(text, label):
    """
    Envía un mensaje de salida a Telegram.

    Este bot NO lee mensajes de usuarios:
    - no usa getUpdates;
    - no usa webhooks;
    - no tiene botones;
    - no procesa comandos.

    Solo utiliza Telegram para enviar los avisos al chat configurado.
    """
    try:
        result = send_message(text)

        if isinstance(result, dict) and result.get("ok") is True:
            print(f"[TELEGRAM] {label}: enviado correctamente.")
            return True

        print(
            f"[TELEGRAM] {label}: respuesta inesperada de Telegram: "
            f"{result!r}"
        )
        return False

    except Exception as exc:
        print(
            f"[TELEGRAM] {label}: ERROR -> "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def main():
    """
    VIGILANCIA ANDALUCÍA v24

    Flujo de cada ejecución:

    1. Consulta INFOCAR/DGT + INFOCA.
    2. Construye la fotografía actual.
    3. ENVÍA SIEMPRE esa fotografía a Telegram.
    4. Si es la primera ejecución, guarda la fotografía como línea base
       y NO genera avisos de cambios.
    5. Si ya existe una línea base:
       - detecta reaperturas por desaparición de una carretera;
       - detecta nuevos cortes;
       - actualiza la línea base con la fotografía actual.
    6. Guarda el estado.

    GitHub Actions se encarga de ejecutar este archivo cada 30 minutos,
    las 24 horas.
    """
    print("=" * 60)
    print("VIGILANCIA ANDALUCÍA v24")
    print("=" * 60)

    state = load_state()

    if not isinstance(state, dict):
        state = {}

    # ------------------------------------------------------------
    # 1. FOTOGRAFÍA ACTUAL
    # ------------------------------------------------------------
    print("[VIGILANCIA] Consultando INFOCAR/DGT + INFOCA...")

    detected = fetch_official_incidents()

    captured_at = datetime.now(TIMEZONE).isoformat()

    print(
        "[VIGILANCIA] Incidentes en la fotografía actual: "
        f"{len(detected)}"
    )

    # ------------------------------------------------------------
    # 2. ENVIAR SIEMPRE LA FOTOGRAFÍA
    # ------------------------------------------------------------
    snapshot = format_snapshot(
        detected,
        captured_at,
    )

    print("[TELEGRAM] Enviando fotografía de estado...")
    _send_telegram(
        snapshot,
        "Fotografía de estado",
    )

    # ------------------------------------------------------------
    # 3. PRIMERA EJECUCIÓN -> CREAR LÍNEA BASE
    # ------------------------------------------------------------
    state.setdefault(
        "monitoring_initialized",
        bool(state.get("incidents")),
    )

    if not state.get("monitoring_initialized"):
        print(
            "[VIGILANCIA] Primera ejecución: "
            "creando línea base."
        )

        initialize_baseline(
            state,
            detected,
        )

        state["monitoring_initialized"] = True
        state["baseline_at"] = captured_at
        state["last_run"] = captured_at
        state["last_snapshot_at"] = captured_at

        save_state(state)

        print(
            "[VIGILANCIA] Línea base creada. "
            "No se generan avisos de cambios en esta ejecución."
        )
        print("=" * 60)
        return

    # ------------------------------------------------------------
    # 4. REAPERTURAS
    # ------------------------------------------------------------
    # Se comprueban antes de process_incidents(), porque aquí todavía
    # tenemos disponible la fotografía anterior en state.
    print(
        "[VIGILANCIA] Comparando con la fotografía anterior "
        "para detectar reaperturas..."
    )

    reopenings = fetch_official_reopenings(
        state,
        detected,
    )

    print(
        "[VIGILANCIA] Reaperturas detectadas: "
        f"{len(reopenings)}"
    )

    for message in process_reopenings(
        state,
        reopenings,
    ):
        print("[TELEGRAM] Enviando aviso de reapertura...")
        _send_telegram(
            message,
            "Aviso de reapertura",
        )

    # ------------------------------------------------------------
    # 5. NUEVOS CORTES / RECIERRES
    # ------------------------------------------------------------
    print(
        "[VIGILANCIA] Comparando con la fotografía anterior "
        "para detectar nuevos cortes..."
    )

    incident_messages = process_incidents(
        state,
        detected,
    )

    print(
        "[VIGILANCIA] Nuevos avisos de corte: "
        f"{len(incident_messages)}"
    )

    for message in incident_messages:
        print("[TELEGRAM] Enviando aviso de corte...")
        _send_telegram(
            message,
            "Aviso de corte",
        )

    # ------------------------------------------------------------
    # 6. GUARDAR LA NUEVA FOTOGRAFÍA COMO REFERENCIA
    # ------------------------------------------------------------
    state["monitoring_initialized"] = True
    state["last_run"] = captured_at
    state["last_snapshot_at"] = captured_at

    save_state(state)

    print(
        "[VIGILANCIA] Fotografía actual guardada como "
        "referencia para la siguiente ejecución."
    )
    print("[VIGILANCIA] Comprobación finalizada.")
    print("=" * 60)


if __name__ == "__main__":
    main()
