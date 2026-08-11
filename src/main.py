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
)
from telegram import send_message


def main():
    """
    Ejecuta UNA comprobación completa de vigilancia.

    Este bot es exclusivamente de salida:
    - No lee mensajes de Telegram.
    - No usa getUpdates.
    - No tiene botones.
    - No procesa comandos de usuarios.

    GitHub Actions ejecuta este archivo cada 30 minutos, las 24 horas.
    """
    print("=" * 60)
    print("VIGILANCIA ANDALUCÍA v18")
    print("=" * 60)

    state = load_state()

    if not isinstance(state, dict):
        state = {}

    # Primera ejecución con estado vacío: tomamos una fotografía inicial.
    # Los cortes que ya existían no generan un aviso; los cambios posteriores
    # sí se notifican.
    state.setdefault("monitoring_initialized", bool(state.get("incidents")))

    if not state.get("monitoring_initialized"):
        print("[VIGILANCIA] Primera ejecución: creando línea base.")

        detected = fetch_official_incidents()

        # Reutilizamos la función existente de lógica para crear la línea base.
        from logic import initialize_baseline

        initialize_baseline(state, detected)
        state["monitoring_initialized"] = True
        state["last_run"] = datetime.now(TIMEZONE).isoformat()

        save_state(state)

        print("[VIGILANCIA] Línea base creada. No se envían avisos en esta ejecución.")
        print("=" * 60)
        return

    # ------------------------------------------------------------
    # 1. Fotografía actual
    # ------------------------------------------------------------
    print("[VIGILANCIA] Consultando fuentes oficiales...")
    detected = fetch_official_incidents()

    print(
        f"[VIGILANCIA] Incidentes detectados en la fotografía actual: "
        f"{len(detected)}"
    )

    # ------------------------------------------------------------
    # 2. Reaperturas
    # ------------------------------------------------------------
    # Se calculan ANTES de actualizar la fotografía almacenada.
    # De esta forma podemos comparar el estado anterior con el actual.
    print("[VIGILANCIA] Comprobando posibles reaperturas...")

    reopenings = fetch_official_reopenings(
        state,
        detected,
    )

    print(
        f"[VIGILANCIA] Posibles reaperturas detectadas: "
        f"{len(reopenings)}"
    )

    for message in process_reopenings(
        state,
        reopenings,
    ):
        print("[TELEGRAM] Enviando aviso de reapertura...")
        send_message(message)

    # ------------------------------------------------------------
    # 3. Nuevos cortes / cambios de estado
    # ------------------------------------------------------------
    print("[VIGILANCIA] Comprobando nuevos cortes...")

    incident_messages = process_incidents(
        state,
        detected,
    )

    print(
        f"[VIGILANCIA] Avisos de nuevos cortes: "
        f"{len(incident_messages)}"
    )

    for message in incident_messages:
        print("[TELEGRAM] Enviando aviso de corte...")
        send_message(message)

    # ------------------------------------------------------------
    # 4. Guardar estado
    # ------------------------------------------------------------
    state["last_run"] = datetime.now(TIMEZONE).isoformat()
    state["monitoring_initialized"] = True

    save_state(state)

    print("[VIGILANCIA] Estado guardado correctamente.")
    print("[VIGILANCIA] Comprobación finalizada.")
    print("=" * 60)


if __name__ == "__main__":
    main()
