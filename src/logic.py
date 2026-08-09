from collections import defaultdict


def normalize(value):
    if value is None:
        return ""

    return str(value).strip().lower()


def incident_key(item):
    """
    Identificador único de una incidencia concreta.

    Se mantiene a nivel de carretera/tramo para poder detectar:
    - nuevos cortes
    - cambios de tramo
    - reaperturas
    """

    return "|".join([
        normalize(item.get("fire")),
        normalize(item.get("province")),
        normalize(item.get("municipality")),
        normalize(item.get("road")),
        normalize(item.get("section")),
        normalize(item.get("direction")),
        normalize(item.get("closure_type")),
    ])


def fire_group_key(item):
    """
    Agrupa las distintas carreteras pertenecientes al mismo incendio.
    """

    return "|".join([
        normalize(item.get("fire")),
        normalize(item.get("province")),
        normalize(item.get("municipality")),
    ])


def format_road(item):
    road = item.get("road") or "No disponible"
    section = item.get("section") or "No disponible"
    direction = item.get("direction") or "No disponible"
    closure_type = item.get("closure_type") or "No disponible"

    return (
        f"🔴 {road}\n"
        f"   Tramo: {section}\n"
        f"   Sentido: {direction}\n"
        f"   Tipo de corte: {closure_type}"
    )


def format_grouped_incident(items):
    """
    Genera un único aviso para un incendio,
    agrupando todas sus carreteras afectadas.
    """

    first = items[0]

    fire = first.get("fire") or "No disponible"
    province = first.get("province") or "No disponible"
    municipality = first.get("municipality") or "No disponible"
    detected_at = first.get("detected_at") or "No disponible"
    fire_status = (
        first.get("fire_status")
        or "No disponible"
    )

    infoca = first.get("infoca") or "No disponible"
    dgt = first.get("dgt") or "No disponible"

    other_sources = set()

    for item in items:
        value = item.get("other_sources")

        if value:
            other_sources.add(str(value))

    roads_text = "\n\n".join(
        format_road(item)
        for item in items
    )

    if other_sources:
        other_text = "\n".join(
            f"• {source}"
            for source in sorted(other_sources)
        )
    else:
        other_text = "No disponible"

    return (
        "🔥 CORTE DE CARRETERAS POR INCENDIO\n\n"
        f"Incendio: {fire}\n"
        f"Provincia: {province}\n"
        f"Municipio: {municipality}\n\n"
        "🚧 Carreteras afectadas:\n\n"
        f"{roads_text}\n\n"
        f"Hora detectada: {detected_at}\n"
        f"Situación del incendio: {fire_status}\n\n"
        f"INFOCA: {infoca}\n"
        f"DGT: {dgt}\n"
        "Otras fuentes oficiales:\n"
        f"{other_text}\n\n"
        "¿Ya lo has atendido?"
    )


def format_reopening(item):
    return (
        "🔓 CARRETERA REABIERTA\n\n"
        f"Incendio: "
        f"{item.get('fire', 'No disponible')}\n"
        f"Carretera: "
        f"{item.get('road', 'No disponible')}\n"
        f"Tramo: "
        f"{item.get('section') or 'No disponible'}\n"
        f"Municipio: "
        f"{item.get('municipality', 'No disponible')}\n"
        f"Provincia: "
        f"{item.get('province', 'No disponible')}\n"
        f"Hora aproximada de reapertura: "
        f"{item.get('reopened_at', 'No disponible')}\n"
        f"Fuente: "
        f"{item.get('source', 'No disponible')}"
    )


def process_incidents(state, detected):
    """
    Procesa nuevos cortes.

    Importante:
    - Cada carretera se mantiene individualmente en el estado.
    - Las nuevas carreteras del mismo incendio se agrupan
      en un único mensaje de Telegram.
    - El mismo corte no vuelve a notificarse.
    """

    alerts = []

    incidents = state.setdefault("incidents", {})

    # ---------------------------------------------------------
    # 1. Eliminar duplicados exactos recibidos en esta ejecución
    # ---------------------------------------------------------

    unique_detected = {}

    for item in detected:
        key = incident_key(item)

        if key not in unique_detected:
            unique_detected[key] = item
        else:
            # Conservamos la información más completa.
            existing = unique_detected[key]

            for k, value in item.items():
                if value not in ("", None, "No disponible"):
                    existing[k] = value

    # ---------------------------------------------------------
    # 2. Determinar cuáles son realmente nuevas
    # ---------------------------------------------------------

    new_items = []

    for key, item in unique_detected.items():

        if key not in incidents:
            incidents[key] = {
                **item,
                "status": "PENDIENTE",
                "notified": True,
                "reopened_notified": False,
                "road_open": False,
            }

            new_items.append(item)

        else:
            # Actualizamos información existente sin crear
            # una nueva alerta.
            incidents[key].update({
                k: v
                for k, v in item.items()
                if v not in ("", None, "No disponible")
            })

    # ---------------------------------------------------------
    # 3. Agrupar nuevas incidencias por incendio
    # ---------------------------------------------------------

    grouped = defaultdict(list)

    for item in new_items:
        grouped[fire_group_key(item)].append(item)

    # ---------------------------------------------------------
    # 4. Crear un único aviso por incendio
    # ---------------------------------------------------------

    for items in grouped.values():

        # Orden estable por carretera
        items.sort(
            key=lambda x: (
                normalize(x.get("road")),
                normalize(x.get("section")),
                normalize(x.get("direction")),
            )
        )

        alerts.append(
            format_grouped_incident(items)
        )

    return alerts


def process_reopenings(state, reopenings):
    """
    Procesa reaperturas.

    Una reapertura solamente se comunica si:
    - la incidencia fue previamente registrada;
    - todavía no se había comunicado su reapertura.
    """

    alerts = []

    incidents = state.setdefault("incidents", {})

    # Evitar duplicados de reapertura dentro de una misma ejecución.
    unique_reopenings = {}

    for item in reopenings:
        key = incident_key(item)

        if key not in unique_reopenings:
            unique_reopenings[key] = item

    for key, item in unique_reopenings.items():

        if key not in incidents:
            continue

        incident = incidents[key]

        if incident.get("reopened_notified"):
            continue

        incident["road_open"] = True
        incident["reopened_notified"] = True
        incident["reopened_at"] = (
            item.get("reopened_at")
        )

        alerts.append(
            format_reopening(item)
        )

    return alerts
