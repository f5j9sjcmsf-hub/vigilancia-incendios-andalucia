def incident_key(item):
    """
    Identifica una incidencia concreta de carretera.

    Se mantiene el detalle de carretera/tramo para poder detectar
    posteriormente reaperturas o nuevos cortes.
    """
    return "|".join([
        item.get("fire", "").strip().lower(),
        item.get("province", "").strip().lower(),
        item.get("municipality", "").strip().lower(),
        item.get("road", "").strip().lower(),
        item.get("section", "").strip().lower(),
        item.get("direction", "").strip().lower(),
        item.get("closure_type", "").strip().lower(),
    ])


def fire_key(item):
    """
    Identifica el incendio independientemente de la fuente.

    Sirve para agrupar varias detecciones del mismo incendio
    en un único mensaje de Telegram.
    """
    return "|".join([
        item.get("fire", "").strip().lower(),
        item.get("province", "").strip().lower(),
        item.get("municipality", "").strip().lower(),
    ])


def format_new_incident_group(items):
    """
    Genera UN SOLO mensaje cuando varias fuentes han detectado
    el mismo incendio y/o varias carreteras afectadas.
    """

    first = items[0]

    message = (
        "🔥 CORTE DE CARRETERA POR INCENDIO\n\n"
        f"Incendio: {first.get('fire') or 'No disponible'}\n"
        f"Provincia: {first.get('province') or 'No disponible'}\n"
        f"Municipio: {first.get('municipality') or 'No disponible'}\n\n"
    )

    # Agrupar carreteras/tramos para evitar repetir información
    roads = []
    seen_roads = set()

    for item in items:
        road = item.get("road") or "Carretera no disponible"
        section = item.get("section") or ""
        direction = item.get("direction") or ""
        closure_type = item.get("closure_type") or ""

        road_key = "|".join([
            road.strip().lower(),
            section.strip().lower(),
            direction.strip().lower(),
            closure_type.strip().lower(),
        ])

        if road_key in seen_roads:
            continue

        seen_roads.add(road_key)

        road_text = f"• {road}"

        if section:
            road_text += f" — {section}"

        if direction:
            road_text += f" — {direction}"

        if closure_type:
            road_text += f" — {closure_type}"

        roads.append(road_text)

    message += "🚧 CARRETERAS AFECTADAS:\n"
    message += "\n".join(roads)

    # Situación del incendio
    fire_status = next(
        (
            item.get("fire_status")
            for item in items
            if item.get("fire_status")
        ),
        None,
    )

    detected_at = next(
        (
            item.get("detected_at")
            for item in items
            if item.get("detected_at")
        ),
        None,
    )

    message += "\n\n"
    message += (
        f"Situación del incendio: "
        f"{fire_status or 'No disponible'}\n"
    )

    message += (
        f"Hora detectada: "
        f"{detected_at or 'No disponible'}\n\n"
    )

    # INFOCA
    infoca = []
    seen_infoca = set()

    for item in items:
        value = item.get("infoca")

        if value and value not in seen_infoca:
            seen_infoca.add(value)
            infoca.append(value)

    message += "INFOCA: "
    message += " | ".join(infoca) if infoca else "No disponible"

    # DGT
    dgt = []
    seen_dgt = set()

    for item in items:
        value = item.get("dgt")

        if value and value not in seen_dgt:
            seen_dgt.add(value)
            dgt.append(value)

    message += "\nDGT: "
    message += " | ".join(dgt) if dgt else "No disponible"

    # Otras fuentes
    other_sources = []
    seen_other = set()

    for item in items:
        value = item.get("other_sources")

        if value and value not in seen_other:
            seen_other.add(value)
            other_sources.append(value)

    if other_sources:
        message += (
            "\nOtras fuentes oficiales: "
            + " | ".join(other_sources)
        )

    message += "\n\n¿Ya lo has atendido?"

    return message


def format_reopening(item):
    return (
        "🔓 CARRETERA REABIERTA\n\n"
        f"Incendio: {item.get('fire') or 'No disponible'}\n"
        f"Carretera: {item.get('road') or 'No disponible'}\n"
        f"Tramo: {item.get('section') or 'No disponible'}\n"
        f"Municipio: {item.get('municipality') or 'No disponible'}\n"
        f"Provincia: {item.get('province') or 'No disponible'}\n"
        f"Hora aproximada de reapertura: "
        f"{item.get('reopened_at') or 'No disponible'}\n"
        f"Fuente: {item.get('source') or 'No disponible'}"
    )


def process_incidents(state, detected):
    """
    Procesa las incidencias nuevas.

    IMPORTANTE:
    - Guarda cada carretera como incidencia independiente.
    - Pero agrupa en UN SOLO mensaje todas las nuevas incidencias
      pertenecientes al mismo incendio.
    """

    alerts = []
    incidents = state.setdefault("incidents", {})

    # ---------------------------------------------------------
    # 1. Eliminar duplicados exactos dentro de la misma ejecución
    # ---------------------------------------------------------

    unique_detected = {}
    
    for item in detected:
        key = incident_key(item)

        if not key:
            continue

        if key not in unique_detected:
            unique_detected[key] = item
        else:
            # Fusionar información procedente de otra fuente
            existing = unique_detected[key]

            for k, v in item.items():
                if v not in ("", None):
                    existing[k] = v

    # ---------------------------------------------------------
    # 2. Detectar cuáles son realmente nuevas
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
            # Actualizar información de la incidencia existente
            incidents[key].update({
                k: v
                for k, v in item.items()
                if v not in ("", None)
            })

    # ---------------------------------------------------------
    # 3. AGRUPAR las nuevas incidencias por incendio
    # ---------------------------------------------------------

    grouped = {}

    for item in new_items:
        key = fire_key(item)

        if key not in grouped:
            grouped[key] = []

        grouped[key].append(item)

    # ---------------------------------------------------------
    # 4. Generar UN mensaje por incendio
    # ---------------------------------------------------------

    for items in grouped.values():
        alerts.append(format_new_incident_group(items))

    return alerts


def process_reopenings(state, reopenings):
    """
    Procesa reaperturas.

    Cada carretera mantiene su propia incidencia para que una
    reapertura pueda detectarse independientemente.
    """

    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in reopenings:

        key = incident_key(item)

        if (
            key in incidents
            and not incidents[key].get("reopened_notified")
        ):

            incidents[key].update({
                "road_open": True,
                "reopened_notified": True,
                "reopened_at": item.get("reopened_at"),
            })

            alerts.append(format_reopening(item))

    return alerts
