from collections import defaultdict


def normalize(value):
    if value is None:
        return ""

    return " ".join(str(value).strip().lower().split())


def incident_key(item):
    """
    Identifica una incidencia concreta de carretera.

    No utilizamos el tipo de corte para identificarla porque
    una misma carretera puede aparecer posteriormente con
    información más precisa.
    """

    return "|".join([
        normalize(item.get("fire")),
        normalize(item.get("province")),
        normalize(item.get("municipality")),
        normalize(item.get("road")),
        normalize(item.get("section")),
        normalize(item.get("direction")),
    ])


def group_key(item):
    """
    Agrupa todas las carreteras pertenecientes al mismo incendio.
    """

    return "|".join([
        normalize(item.get("fire")),
        normalize(item.get("province")),
        normalize(item.get("municipality")),
    ])


def format_new_incident_group(items):
    """
    Genera UN SOLO mensaje para todas las carreteras afectadas
    por el mismo incendio.
    """

    first = items[0]

    message = (
        "🔥 CORTE DE CARRETERA POR INCENDIO\n\n"
        f"Incendio: {first.get('fire') or 'No disponible'}\n"
        f"Provincia: {first.get('province') or 'No disponible'}\n"
        f"Municipio: {first.get('municipality') or 'No disponible'}\n\n"
        "🚧 CARRETERAS AFECTADAS\n"
    )

    for item in items:
        road = item.get("road") or "Carretera no disponible"
        section = item.get("section") or "Tramo no disponible"
        direction = item.get("direction") or "Sentido no disponible"
        closure_type = (
            item.get("closure_type")
            or "Tipo de corte no disponible"
        )

        message += (
            f"\n• {road}\n"
            f"  Tramo: {section}\n"
            f"  Sentido: {direction}\n"
            f"  Corte: {closure_type}\n"
        )

    fire_status = first.get("fire_status") or "No disponible"

    message += (
        "\n"
        f"Situación del incendio: {fire_status}\n\n"
        f"INFOCA: {first.get('infoca') or 'No disponible'}\n"
        f"DGT: {first.get('dgt') or 'No disponible'}\n"
    )

    # Recopilamos fuentes oficiales sin repetirlas.
    sources = []

    for item in items:
        source = item.get("source_url") or item.get("other_sources")

        if source and source not in sources:
            sources.append(source)

    if sources:
        message += "\nOtras fuentes oficiales:\n"

        for source in sources[:5]:
            message += f"• {source}\n"

    message += "\n¿Ya lo has atendido?"

    return message


def format_reopening(item):
    return (
        "🔓 CARRETERA REABIERTA\n\n"
        f"Incendio: {item.get('fire') or 'No disponible'}\n"
        f"Carretera: {item.get('road') or 'No disponible'}\n"
        f"Tramo: {item.get('section') or 'No disponible'}\n"
        f"Municipio: "
        f"{item.get('municipality') or 'No disponible'}\n"
        f"Provincia: "
        f"{item.get('province') or 'No disponible'}\n"
        f"Hora aproximada de reapertura: "
        f"{item.get('reopened_at') or 'No disponible'}\n"
        f"Fuente: "
        f"{item.get('source') or 'No disponible'}"
    )


def process_incidents(state, detected):
    """
    Procesa las incidencias detectadas.

    Mantiene las carreteras individualmente en el estado,
    pero agrupa las nuevas alertas por incendio.

    Resultado:
        - varias carreteras del mismo incendio
          -> UN SOLO mensaje Telegram.
        - mismo corte detectado varias veces
          -> ningún mensaje adicional.
    """

    alerts = []

    incidents = state.setdefault("incidents", {})

    # ------------------------------------------------------------
    # 1. Eliminar duplicados dentro de la misma ejecución
    # ------------------------------------------------------------

    unique_detected = {}

    for item in detected:
        key = incident_key(item)

        if key not in unique_detected:
            unique_detected[key] = item
        else:
            # Conservamos la información más completa.
            existing = unique_detected[key]

            for field, value in item.items():
                if value not in ("", None, "No disponible"):
                    existing[field] = value

    # ------------------------------------------------------------
    # 2. Registrar únicamente incidencias nuevas
    # ------------------------------------------------------------

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
            # Actualizamos la información existente sin generar
            # una nueva alerta.
            incidents[key].update({
                k: v
                for k, v in item.items()
                if v not in ("", None, "No disponible")
            })

    # ------------------------------------------------------------
    # 3. AGRUPAR LAS NUEVAS INCIDENCIAS POR INCENDIO
    # ------------------------------------------------------------

    grouped = defaultdict(list)

    for item in new_items:
        grouped[group_key(item)].append(item)

    # ------------------------------------------------------------
    # 4. Generar un solo mensaje por incendio
    # ------------------------------------------------------------

    for items in grouped.values():
        alerts.append(
            format_new_incident_group(items)
        )

    return alerts


def process_reopenings(state, reopenings):
    """
    Procesa reaperturas.

    Una reapertura se comunica una sola vez.
    """

    alerts = []

    incidents = state.setdefault("incidents", {})

    # Evitar duplicados de reapertura dentro de la misma ejecución.
    processed = set()

    for item in reopenings:

        key = incident_key(item)

        if key in processed:
            continue

        processed.add(key)

        if (
            key in incidents
            and not incidents[key].get("reopened_notified")
        ):

            incidents[key]["road_open"] = True
            incidents[key]["reopened_notified"] = True

            alerts.append(
                format_reopening(item)
            )

    return alerts
