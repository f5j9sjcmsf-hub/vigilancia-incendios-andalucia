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
)
from telegram import send_message


def _send_telegram(text, label):
    """
    Envía un mensaje a Telegram y deja constancia en los logs.
    No lee mensajes de usuarios, no usa getUpdates y no crea botones.
    """
    try:
        result = send_message(text)

        if isinstance(result, dict) and result.get("ok") is True:
            print(f"[TELEGRAM] {label}: enviado correctamente.")
            return True

        print(
            f"[TELEGRAM] {label}: respuesta inesperada de la API: "
            f"{result!r}"
        )
        return False

    except Exception as exc:
        print(
            f"[TELEGRAM] {label}: ERROR al enviar -> "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def main():
    """
    VIGILANCIA ANDALUCÍA v19

    - Solo salida.
    - NO lee mensajes de Telegram.
    - NO usa getUpdates.
    - NO usa botones.
    - NO procesa comandos.
    - GitHub Actions ejecuta este archivo cada 30 minutos, 24 horas.

    En la primera ejecución de v19 se envía UNA sola prueba automática
    a TELEGRAM_CHAT_ID para confirmar que Telegram funciona. Después
    queda registrada en state.json y no vuelve a enviarse.
    """
    print("=" * 60)
    print("VIGILANCIA ANDALUCÍA v19")
    print("=" * 60)

    state = load_state()

    if not isinstance(state, dict):
        state = {}

    # ------------------------------------------------------------
    # 0. PRUEBA ÚNICA DE TELEGRAM
    # ------------------------------------------------------------
    if not state.get("telegram_test_sent"):
        print("[TELEGRAM] Ejecutando prueba única de conexión...")

        sent = _send_telegram(
            (
                "🤖 <b>🔥IIFF Andalucía</b>\n\n"
                "Conexión con Telegram confirmada correctamente.\n\n"
                "La vigilancia está funcionando en modo automático "
                "y sin botones ni comandos.\n"
                "Se comprobarán las carreteras cada 30 minutos."
            ),
            "Prueba inicial",
        )

        if sent:
            state["telegram_test_sent"] = True
            save_state(state)
        else:
            print(
                "[TELEGRAM] La prueba NO se ha podido enviar. "
                "Revisar el error anterior."
            )

    # ------------------------------------------------------------
    # 1. LÍNEA BASE INICIAL
    # ------------------------------------------------------------
    state.setdefault(
        "monitoring_initialized",
        bool(state.get("incidents")),
    )

    if not state.get("monitoring_initialized"):
        print("[VIGILANCIA] Primera ejecución: creando línea base.")

        detected = fetch_official_incidents()

        initialize_baseline(
            state,
            detected,
        )

        state["monitoring_initialized"] = True
        state["last_run"] = datetime.now(TIMEZONE).isoformat()

        save_state(state)

        print(
            "[VIGILANCIA] Línea base creada. "
            "No se envían avisos de cortes existentes."
        )
        print("=" * 60)
        return

    # ------------------------------------------------------------
    # 2. FOTOGRAFÍA ACTUAL
    # ------------------------------------------------------------
    print("[VIGILANCIA] Consultando fuentes oficiales...")

    detected = fetch_official_incidents()

    print(
        "[VIGILANCIA] Incidentes detectados en la fotografía actual: "
        f"{len(detected)}"
    )

    # ------------------------------------------------------------
    # 3. REAPERTURAS
    # ------------------------------------------------------------
    print("[VIGILANCIA] Comprobando posibles reaperturas...")

    reopenings = fetch_official_reopenings(
        state,
        detected,
    )

    print(
        "[VIGILANCIA] Posibles reaperturas detectadas: "
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
    # 4. NUEVOS CORTES / NUEVOS CIERRES
    # ------------------------------------------------------------
    print("[VIGILANCIA] Comprobando nuevos cortes...")

    incident_messages = process_incidents(
        state,
        detected,
    )

    print(
        "[VIGILANCIA] Avisos de nuevos cortes: "
        f"{len(incident_messages)}"
    )

    for message in incident_messages:
        print("[TELEGRAM] Enviando aviso de corte...")
        _send_telegram(
            message,
            "Aviso de corte",
        )

    # ------------------------------------------------------------
    # 5. GUARDAR ESTADO
    # ------------------------------------------------------------
    state["last_run"] = datetime.now(TIMEZONE).isoformat()
    state["monitoring_initialized"] = True

    save_state(state)

    print("[VIGILANCIA] Estado guardado correctamente.")
    print("[VIGILANCIA] Comprobación finalizada.")
    print("=" * 60)


if __name__ == "__main__":
    main()
