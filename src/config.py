import os
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Europe/Madrid")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


ANDALUSIA_PROVINCES = {
    "Almería",
    "Cádiz",
    "Córdoba",
    "Granada",
    "Huelva",
    "Jaén",
    "Málaga",
    "Sevilla",
}
