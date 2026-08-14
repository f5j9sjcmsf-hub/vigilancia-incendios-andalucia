# Vigilancia de cortes por incendios en Andalucía

Bot de Telegram que vigila los cortes y reaperturas de carreteras causados
por incendios forestales en las ocho provincias andaluzas.

## Funcionamiento

- INFOCAR/DGT DATEX II es la fuente de verdad de los cortes y reaperturas.
- El filtro regional usa los campos oficiales de comunidad, provincia y
  municipio del propio feed; no depende de un incendio concreto.
- INFOCA se usa únicamente para enriquecer internamente la identificación
  cuando existe una coincidencia clara.
- Los mensajes de Telegram no muestran noticias, titulares ni enlaces.
- Los cortes DGT sin coincidencia INFOCA también se notifican.
- Una carretera añadida a un incendio existente genera un nuevo aviso.
- Un cambio real en el tramo kilométrico genera un aviso de actualización.
- Las reaperturas se deduplican y un cierre posterior vuelve a notificarse.

La vigilancia se inicia manualmente una sola vez mediante `workflow_dispatch`.
Cada ejecución comprueba las fuentes cada 15 minutos durante unos 75 minutos y
lanza directamente su siguiente relevo. No existen disparos `schedule` que
puedan solaparse o ser descartados por GitHub. Si la vigilancia falla, el job de
relevo espera 15 minutos antes de reintentarlo; una cancelación manual sí detiene
la cadena. Telegram solo recibe una línea base al inicializar el estado y,
después, avisos cuando cambian realmente los cortes o reaperturas. Si la
fotografía oficial no cambia, no se repite ningún informe.

## Fiabilidad

- Si INFOCAR/DGT no responde, la ejecución falla y no interpreta el error
  como ausencia de cortes.
- Si Telegram no confirma un envío, el estado no avanza y el aviso se
  reintenta en la ejecución siguiente.
- El relevo se ejecuta en un job independiente incluso tras un fallo temporal.
- El estado se escribe de forma atómica en `data/state.json`.
- El workflow ejecuta las pruebas antes de consultar las fuentes reales.

## Secretos de GitHub

En `Settings → Secrets and variables → Actions` deben existir:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

El token nunca debe publicarse en el repositorio.
