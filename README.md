# Vigilancia de cortes de carretera por incendios forestales en Andalucía

Bot de Telegram para detectar nuevos cortes y reaperturas de carreteras causados por incendios forestales en Andalucía.

Arquitectura inicial:
- Python 3.12
- GitHub Actions
- Telegram Bot API
- zona horaria `Europe/Madrid`
- ejecución horaria a los 07 minutos, de 09:07 a 22:07

La integración de fuentes oficiales se mantiene separada para poder verificar y adaptar los endpoints oficiales antes de activar alertas de producción.

## Secretos de GitHub

En `Settings -> Secrets and variables -> Actions` crear:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Nunca publiques el token en el repositorio.
