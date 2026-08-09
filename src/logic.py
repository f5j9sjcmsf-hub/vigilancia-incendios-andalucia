from datetime import datetime


def normalize(value):
    if value is None:
        return ""

    return " ".join(
        str(value).strip().lower().split()
    )


def clean_municipality(value):
    """
    Limpia contaminaciones del tipo:

        Niebla (Huelva)
        Niebla (Huelva) (Granada)
        Niebla - Portavoz del Gobierno Andaluz
    """

    if not value:
        return ""

    value = str(value).strip()

    # Eliminar todo lo que venga entre paréntesis.
    value = value.split("(")[0]

    # Eliminar restos de titulares.
    separators = [
        " - ",
        " — ",
        " – ",
        " pese a ",
        " uno de ",
        " y hasta ",
        " con ",
    ]

    lower = value.lower()

    for separator in separators:
        position = lower.find(
            separator.lower()
        )

        if position != -1:
            value = value[:position]
            lower = value.lower()

    return value.strip(
        " .,:;–—-"
    )


def clean_fire_name(value):
    """
    Normaliza nombres como:

        Incendio de Niebla
        Incendio de Niebla (Huelva)
        Incendio de Niebla pese a los continuos cambios de viento
    """

    if not value:
        return "Incendio forestal"

    value = str(value).strip()

    value = value.split("(")[0]

    lower = value.lower()

    # Cortar titulares contaminados.
    separators = [
        " - ",
        " — ",
        " – ",
        " pese a ",
        " uno de ",
        " con ",
        " y hasta ",
    ]

    for separator in separators:

        position = lower.find(
            separator.lower()
        )

        if position != -1:
            value = value[:position]
            lower = value.lower()

    value = value.strip(
        " .,:;–—-"
    )

    # Normalizar variantes.
    if lower.startswith(
        "incendio de "
    ):
        return value

    if lower.startswith(
        "incendio "
    ):
        return value

    return f"Incendio de {value}"


def get_fire_key(item):
    """
    La clave identifica el incendio por:

        provincia + municipio

    y NO por el titular de la noticia.
    """

    municipality = clean_municipality(
        item.get("municipality")
    )

    province = clean_municipality(
        item.get("province")
    )

    if municipality:
        return (
            f"{normalize(province)}|"
            f"{normalize(municipality)}"
        )

    fire = clean_fire_name(
        item.get("fire")
    )

    return (
        f"{normalize(province)}|"
        f"{normalize(fire)}"
    )


def split_roads(value):

    if not value:
        return []

    result = [str(value)]

    separators = [
        ",",
        ";",
        " / ",
        " | ",
    ]

    for separator in separators:

        new_result = []

        for part in result:
            new_result.extend(
                part.split(separator)
            )

        result = new_result

    cleaned = []

    for road in result:

        road = road.strip()

        if not road:
            continue

        if road.lower() == "no disponible":
            continue

        if road not in cleaned:
            cleaned.append(
                road
            )

    return cleaned


def merge_roads(existing, new):

    roads = []

    for value in (
        existing,
        new,
    ):

        for road in split_roads(value):

            if road not in roads:
                roads.append(
                    road
                )

    return ", ".join(roads)


def format_time(value):
    """
    Convierte una fecha ISO a:

        DD/MM/YYYY HH:MM

    Ejemplo:

        09/08/2026 08:52
    """

    if not value:
        return "No disponible"

    try:

        text = str(value)

        if "T" in text:

            dt = datetime.fromisoformat(
                text.replace(
                    "Z",
                    "+00:00"
                )
            )

            return dt.strftime(
                "%d/%m/%Y %H:%M"
            )

    except Exception:
        pass

    return str(value)


def format_sources(value):

    if not value:
        return "• No disponible"

    if isinstance(
        value,
        list
    ):
        sources = value

    else:
        sources = [
            item.strip()
            for item in str(value).split("|")
            if item.strip()
        ]

    lines = []

    for source in sources:

        lines.append(
            f"• {source}"
        )

    return "\n".join(
        lines
    )


def format_new_incident(item):

    fire = clean_fire_name(
        item.get("fire")
    )

    province = clean_municipality(
        item.get("province")
    )

    municipality = clean_municipality(
        item.get("municipality")
    )

    roads = split_roads(
        item.get("road")
    )

    section = item.get(
        "section"
    )

    detected_at = format_time(
        item.get("detected_at")
    )

    infoca = item.get(
        "infoca"
    ) or "No disponible"

    dgt = item.get(
        "dgt"
    ) or "No disponible"

    sources = format_sources(
        item.get("other_sources")
    )

    # --------------------------------------------------------
    # CARRETERAS
    # --------------------------------------------------------

    road_lines = []

    for road in roads:

        if (
            section
            and section != "No disponible"
        ):

            road_lines.append(
                f"• <b>{road}</b> — "
                f"<i>{section}</i>"
            )

        else:

            road_lines.append(
                f"• <b>{road}</b>"
            )

    if not road_lines:

        road_lines.append(
            "• No disponible"
        )

    roads_text = "\n".join(
        road_lines
    )

    return (
        "🔥 <b>CORTE DE CARRETERA "
        "POR INCENDIO</b>\n\n"

        f"<i>{fire}</i>\n\n"

        f"📍 {municipality} "
        f"({province})\n\n"

        "🚧 <b>CARRETERAS AFECTADAS</b>\n"
        f"{roads_text}\n\n"

        f"🕐 Detectado: "
        f"<b>{detected_at}</b>\n\n"

        f"Situación: "
        f"{item.get('fire_status') or 'No disponible'}\n\n"

        f"INFOCA: {infoca}\n"
        f"DGT: {dgt}\n\n"

        "<b>Fuentes oficiales:</b>\n"
        f"{sources}\n\n"

        "¿Ya lo has atendido?"
    )


def format_reopening(item):

    fire = clean_fire_name(
        item.get("fire")
    )

    road = item.get(
        "road",
        "No disponible"
    )

    section = item.get(
        "section"
    )

    municipality = clean_municipality(
        item.get("municipality")
    )

    province = clean_municipality(
        item.get("province")
    )

    reopened_at = format_time(
        item.get("reopened_at")
    )

    source = item.get(
        "source",
        "No disponible"
    )

    if (
        section
        and section != "No disponible"
    ):

        road_text = (
            f"<b>{road}</b> — "
            f"<i>{section}</i>"
        )

    else:

        road_text = (
            f"<b>{road}</b>"
        )

    return (
        "🔓 <b>CARRETERA REABIERTA</b>\n\n"

        f"<i>{fire}</i>\n\n"

        f"📍 {municipality} "
        f"({province})\n\n"

        f"🚧 {road_text}\n\n"

        f"🕐 Reabierta: "
        f"<b>{reopened_at}</b>\n\n"

        "Fuente oficial:\n"
        f"• {source}"
    )


def process_incidents(
    state,
    detected
):

    alerts = []

    incidents = state.setdefault(
        "incidents",
        {}
    )

    for item in detected:

        # ----------------------------------------------------
        # NORMALIZAR ANTES DE AGRUPAR
        # ----------------------------------------------------

        item = dict(item)

        item["municipality"] = (
            clean_municipality(
                item.get(
                    "municipality"
                )
            )
        )

        item["province"] = (
            clean_municipality(
                item.get(
                    "province"
                )
            )
        )

        item["fire"] = (
            clean_fire_name(
                item.get(
                    "fire"
                )
            )
        )

        key = get_fire_key(
            item
        )

        roads = split_roads(
            item.get("road")
        )

        # ----------------------------------------------------
        # NUEVA INCIDENCIA
        # ----------------------------------------------------

        if key not in incidents:

            stored = {
                **item,
                "road": ", ".join(
                    roads
                ),
                "status": "PENDIENTE",
                "notified": True,
                "reopened_notified": False,
            }

            incidents[key] = stored

            alerts.append(
                format_new_incident(
                    stored
                )
            )

            continue

        # ----------------------------------------------------
        # INCIDENCIA YA EXISTENTE
        # ----------------------------------------------------

        existing = incidents[key]

        existing_roads = split_roads(
            existing.get("road")
        )

        merged_roads = []

        for road in (
            existing_roads
            + roads
        ):

            if road not in merged_roads:

                merged_roads.append(
                    road
                )

        # Actualizar información.
        for field, value in item.items():

            if value in (
                "",
                None,
                "No disponible",
            ):
                continue

            existing[field] = value

        existing["fire"] = clean_fire_name(
            existing.get("fire")
        )

        existing["municipality"] = (
            clean_municipality(
                existing.get(
                    "municipality"
                )
            )
        )

        existing["province"] = (
            clean_municipality(
                existing.get(
                    "province"
                )
            )
        )

        existing["road"] = ", ".join(
            merged_roads
        )

        # ----------------------------------------------------
        # IMPORTANTE:
        # NO GENERAR OTRO AVISO POR OTRA NOTICIA
        # DEL MISMO INCENDIO.
        # ----------------------------------------------------

    return alerts


def process_reopenings(
    state,
    reopenings
):

    alerts = []

    incidents = state.setdefault(
        "incidents",
        {}
    )

    for item in reopenings:

        key = get_fire_key(
            item
        )

        if key not in incidents:
            continue

        incident = incidents[key]

        if incident.get(
            "reopened_notified"
        ):
            continue

        incident[
            "road_open"
        ] = True

        incident[
            "reopened_notified"
        ] = True

        alerts.append(
            format_reopening(
                {
                    **incident,
                    **item,
                }
            )
        )

    return alerts
