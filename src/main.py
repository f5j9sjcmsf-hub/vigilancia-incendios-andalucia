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
    state = load_state()

    # Fotografía actual de INFOCAR + INFOCA.
    detected = fetch_official_incidents()

    # Comparamos la fotografía actual con la anterior almacenada.
    # Las desapariciones de INFOCAR generan posibles reaperturas.
    reopenings = fetch_official_reopenings(
        state,
        detected,
    )

    # Procesamos primero las reaperturas para poder actualizar
    # correctamente el estado de las carreteras.
    for message in process_reopenings(state, reopenings):
        send_message(message)

    # Después actualizamos la fotografía actual del incendio.
    for message in process_incidents(state, detected):
        send_message(message)

    state["last_run"] = datetime.now(TIMEZONE).isoformat()

    save_state(state)


if __name__ == "__main__":
    main()
