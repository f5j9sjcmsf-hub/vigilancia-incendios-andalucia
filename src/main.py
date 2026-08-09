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

    detected = fetch_official_incidents()
    reopenings = fetch_official_reopenings()

    for message in process_incidents(state, detected):
        send_message(message)

    for message in process_reopenings(state, reopenings):
        send_message(message)

    state["last_run"] = datetime.now(TIMEZONE).isoformat()

    save_state(state)


if __name__ == "__main__":
    main()
