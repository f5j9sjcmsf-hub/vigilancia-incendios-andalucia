def normalize(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def incident_key(item):
    """
    Agrupa una incidencia por:
    incendio + provincia + municipio + carretera.

    No utilizamos tramo, sentido ni tipo de corte como parte
    de la clave porque queremos agruparlos dentro de un mismo aviso.
    """

    return "|".join([
        normalize(item.get("fire")),
        normalize(item.get("province")),
        normalize(item.get("municipality")),
        normalize(item.get("road")),
    ])


def unique_values(values):
    """
    Elimina duplicados conservando el orden.
    """
    result = []

    for value in values:
        if not value:
            continue

        value = str(value).strip()

        if value and value not in result:
            result.append(value)

    return result


def merge_incidents(items):
    """
    Agrupa varias detecciones que pertenecen al mismo incendio
    y carretera.
    """

    groups = {}

    for item in items:
        key = incident_key(item)

        if key not in groups:
            groups[key] = {
                **item,
                "sections": [],
                "directions": [],
                "closure_types": [],
                "sources": [],
            }

        group = groups[key]

        section = item.get("section")
        direction = item.get("direction")
        closure_type = item.get("closure_type")
        source = item.get("source_url") or item.get("other_sources")

        if section and section != "No disponible":
            group["sections"].append(section)

        if direction and direction != "No disponible":
            group["directions"].append(direction)

        if closure_type and closure_type != "No disponible":
            group["closure_types"].append(closure_type)

        if source:
            group["sources"].append(source)

        # Conservamos información útil de las distintas fuentes.
        for field in (
            "fire_status",
            "infoca",
            "dgt",
            "other_sources",
            "source_url",
            "source_title",
        ):
            value = item.get(field)

            if value not in ("", None, "No disponible"):
                group[field] = value

    # Limpiamos duplicados
    for group in groups.values():
        group["sections"] = unique_values(group["sections"])
        group["directions"] = unique_values(group["directions"])
        group["closure_types"] = unique_values(group["closure_types"])
        group["sources"] = unique_values(group["sources"])

    return list(groups.values())


def format_list(values, fallback="No disponible"):
    if not values:
        return fallback

    return "\n".join(
        f"• {value}"
        for value in values
    )


def format_new_incident(item):
    sections = item.get("sections", [])
    directions = item.get("directions", [])
    closure_types = item.get("closure_types", [])

    return (
        "🔥 CORTE DE CARRETERA POR INCENDIO\n\n"

        f"Incendio: {item.get('fire') or 'No disponible'}\n"
        f"Provincia: {item.get('province') or 'No disponible'}\n"
        f"Municipio: {item.get('municipality') or 'No disponible'}\n"
        f"Carretera: {item.get('road') or 'No disponible'}\n\n"

        "Tramos afectados:\n"
        f"{format_list(sections)}\n\n"

        "Sentido:\n"
        f"{format_list(directions)}\n\n"

        f"Tipo de corte: "
        f"{', '.join(closure_types) if closure_types else 'No disponible'}\n"

        f"Hora detectada: "
        f"{item.get('detected_at') or 'No disponible'}\n"

        f"Situación del incendio: "
        f"{item.get('fire_status') or 'No disponible'}\n\n"

        f"INFOCA: "
        f"{item.get('infoca') or 'No disponible'}\n"

        f"DGT: "
        f"{item.get('dgt') or 'No disponible'}\n"

        f"Otras fuentes oficiales: "
        f"{item.get('other_sources') or 'No disponible'}\n\n"

        "¿Ya lo has atendido?"
    )


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
    Procesa las incidencias detectadas.

    Primero agrupa todas las detecciones pertenecientes al mismo
    incendio y carretera.

    Después compara contra el estado persistente para evitar
    repetir avisos.
    """

    alerts = []

    incidents = state.setdefault("incidents", {})

    # ============================================================
    # AGRUPAR ANTES DE COMPARAR CON EL ESTADO
    # ============================================================

    grouped = merge_incidents(detected)

    for item in grouped:
        key = incident_key(item)

        # --------------------------------------------------------
        # NUEVA INCIDENCIA
        # --------------------------------------------------------

        if key not in incidents:

            incidents[key] = {
                **item,
                "status": "PENDIENTE",
                "notified": True,
                "reopened_notified": False,
                "road_open": False,
            }

            alerts.append(
                format_new_incident(item)
            )

            continue

        # --------------------------------------------------------
        # INCIDENCIA YA CONOCIDA
        # --------------------------------------------------------

        existing = incidents[key]

        # Actualizamos los datos básicos
        for field, value in item.items():

            if field in (
                "sections",
                "directions",
                "closure_types",
                "sources",
            ):
                continue

            if value not in ("", None, "No disponible"):
                existing[field] = value

        # Fusionamos información acumulada
        existing["sections"] = unique_values(
            existing.get("sections", [])
            + item.get("sections", [])
        )

        existing["directions"] = unique_values(
            existing.get("directions", [])
            + item.get("directions", [])
        )

        existing["closure_types"] = unique_values(
            existing.get("closure_types", [])
            + item.get("closure_types", [])
        )

        existing["sources"] = unique_values(
            existing.get("sources", [])
            + item.get("sources", [])
        )

    return alerts


def process_reopenings(state, reopenings):
    """
    Procesa reaperturas.

    Una reapertura solamente se notifica si la incidencia
    había sido previamente detectada.
    """

    alerts = []

    incidents = state.setdefault("incidents", {})

    # También agrupamos las reaperturas.
    grouped = merge_incidents(reopenings)

    for item in grouped:

        key = incident_key(item)

        if key not in incidents:
            continue

        incident = incidents[key]

        if incident.get("reopened_notified"):
            continue

        incident["road_open"] = True
        incident["reopened_notified"] = True
        incident["status"] = "REABIERTA"

        # Conservamos información de reapertura.
        incident["reopened_at"] = (
            item.get("reopened_at")
            or incident.get("reopened_at")
        )

        incident["reopening_source"] = (
            item.get("source")
            or item.get("source_url")
            or incident.get("source_url")
        )

        alerts.append(
            format_reopening(item)
        )

    return alerts
