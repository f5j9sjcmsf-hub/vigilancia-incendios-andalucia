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
    # Cargamos primero la fotografía anterior guardada en storage.
    state = load_state()

    # Obtenemos la fotografía ACTUAL de INFOCAR + INFOCA.
    detected = fetch_official_incidents()

    # IMPORTANTE: la reapertura se calcula contra el estado anterior,
    # antes de que process_incidents sustituya la fotografía almacenada.
    reopenings = fetch_official_reopenings(
        state,
        detected,
    )

    # Primero notificamos las reaperturas y actualizamos el estado para que
    # una carretera que ha reabierto deje de figurar como activa.
    for message in process_reopenings(
        state,
        reopenings,
    ):
        send_message(message)

    # Después guardamos la fotografía actual de INFOCAR.
    for message in process_incidents(
        state,
        detected,
    ):
        send_message(message)

    state["last_run"] = datetime.now(
        TIMEZONE
    ).isoformat()

    save_state(state)


if __name__ == "__main__":
    main()
