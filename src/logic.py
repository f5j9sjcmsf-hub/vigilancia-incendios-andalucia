from datetime import datetime


def normalize(value):
    if value is None:
        return ""

    return " ".join(
        str(value).strip().lower().split()
    )


def get_fire_key(item):
    """
    Identifica el incendio independientemente de cómo
    lo haya escrito cada noticia.

    Ejemplo:

        Incendio de Niebla
        Incendio de Niebla (Huelva)
        Niebla

    deben acabar agrupándose.
    """

    municipality = normalize(
        item.get("municipality")
    )

    province = normalize(
        item.get("province")
    )

    if municipality and municipality != "no disponible":
        return f"{province}|{municipality}"

    fire = normalize(
        item.get("fire")
    )

    fire = fire.replace(
        "incendio forestal de ",
        ""
    )

    fire = fire.replace(
        "incendio forestal ",
        ""
    )

    fire = fire.replace(
        "incendio de ",
        ""
    )

    fire = fire.replace(
        "incendio ",
        ""
    )

    return f"{province}|{fire}"


def split_roads(value):
    """
    Convierte:

        HU-3106, A-493, HU-4103

    en:

        ["HU-3106", "A-493", "HU-4103"]
    """

    if not value:
        return []

    separators = [
        ",",
        ";",
        " / ",
        " - ",
    ]

    result = [str(value)]

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
            cleaned.append(road)

    return cleaned


def merge_roads(existing, new):
    """
    Une las carreteras de varias fuentes sin duplicarlas.
    """

    roads = []

    for value in (
        existing,
        new,
    ):

        for road in split_roads(value):

            if road not in roads:
                roads.append(road)

    return ", ".join(roads)


def format_time(value):
    """
    Convierte:

        2026-08-09T08:43:41.190687+00:00

    en:

        08:43

    Si no puede interpretarlo, devuelve el valor original.
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

            return dt.strftime("%H:%M")

    except Exception:
        pass

    return str(value)


def format_sources(value):
    """
    Convierte varias URLs separadas por | en una lista HTML.
    """

    if not value:
        return "• No disponible"

    if isinstance(value, list):
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

    return "\n".join(lines)


def format_new_incident(item):

    fire = item.get(
        "fire",
        "Incendio forestal"
    )

    province = item.get(
        "province",
        "No disponible"
    )

    municipality = item.get(
        "municipality",
        "No disponible"
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

        if section and section != "No disponible":
            road_lines.append(
                f"• <b>{road}</b> — <i>{section}</i>"
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
        "🔥 <b>CORTE DE CARRETERA POR INCENDIO</b>\n\n"

        f"<i>{fire}</i>\n\n"

        f"📍 {municipality} ({province})\n\n"

        "🚧 <b>CARRETERAS AFECTADAS</b>\n"
        f"{roads_text}\n\n"

        f"🕐 Detectado: <b>{detected_at}</b>\n\n"

        f"Situación: {item.get('fire_status') or 'No disponible'}\n\n"

        f"INFOCA: {infoca}\n"
        f"DGT: {dgt}\n\n"

        "<b>Fuentes oficiales:</b>\n"
        f"{sources}\n\n"

        "¿Ya lo has atendido?"
    )


def format_reopening(item):

    fire = item.get(
        "fire",
        "Incendio forestal"
    )

    road = item.get(
        "road",
        "No disponible"
    )

    section = item.get(
        "section"
    )

    municipality = item.get(
        "municipality",
        "No disponible"
    )

    province = item.get(
        "province",
        "No disponible"
    )

    reopened_at = format_time(
        item.get("reopened_at")
    )

    source = item.get(
        "source",
        "No disponible"
    )

    if section and section != "No disponible":
        road_text = (
            f"<b>{road}</b> — "
            f"<i>{section}</i>"
        )
    else:
        road_text = f"<b>{road}</b>"

    return (
        "🔓 <b>CARRETERA REABIERTA</b>\n\n"

        f"<i>{fire}</i>\n\n"

        f"📍 {municipality} ({province})\n\n"

        f"🚧 {road_text}\n\n"

        f"🕐 Reabierta: <b>{reopened_at}</b>\n\n"

        f"Fuente oficial:\n"
        f"• {source}"
    )


def process_incidents(state, detected):

    alerts = []

    incidents = state.setdefault(
        "incidents",
        {}
    )

    for item in detected:

        key = get_fire_key(item)

        roads = split_roads(
            item.get("road")
        )

        # ----------------------------------------------------
        # NUEVO INCENDIO / NUEVA INCIDENCIA
        # ----------------------------------------------------

        if key not in incidents:

            stored = {
                **item,
                "road": ", ".join(roads),
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
        # INCENDIO YA CONOCIDO
        # ----------------------------------------------------

        existing = incidents[key]

        old_roads = split_roads(
            existing.get("road")
        )

        merged_roads = []

        for road in old_roads + roads:

            if road not in merged_roads:
                merged_roads.append(
                    road
                )

        old_road_string = ", ".join(
            old_roads
        )

        new_road_string = ", ".join(
            merged_roads
        )

        # Actualizamos información,
        # pero NO mandamos otro aviso
        # por otra noticia del mismo incendio.

        existing.update({
            k: v
            for k, v in item.items()
            if v not in (
                "",
                None,
                "No disponible",
            )
        })

        existing["road"] = new_road_string

        # ----------------------------------------------------
        # SOLO NUEVO AVISO SI APARECE UN NUEVO CORTE REAL
        # ----------------------------------------------------

        if (
            new_road_string != old_road_string
            and old_roads
        ):

            # Es una carretera nueva relacionada con
            # el mismo incendio.
            #
            # De momento la añadimos al estado,
            # pero NO generamos un aviso duplicado.
            pass

    return alerts


def process_reopenings(state, reopenings):

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

        incident["road_open"] = True

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
