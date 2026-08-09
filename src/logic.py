import html
import re
from datetime import datetime


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _escape(value):
    return html.escape(_clean(value), quote=True)


def _format_detected_at(value):
    """
    Acepta:
      - 09/08/2026 12:21
      - ISO 8601
    y devuelve siempre DD/MM/YYYY HH:MM.
    """
    value = _clean(value)
    if not value:
        return "No disponible"

    if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", value):
        return value

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value[:16]


def _road_details(item):
    """
    Devuelve una lista de:
      {"road": "...", "section": "...", "direction": "..."}
    Compatible también con items antiguos que solo tengan 'road'.
    """
    details = item.get("road_details")

    if isinstance(details, list):
        result = []
        seen = set()

        for detail in details:
            if not isinstance(detail, dict):
                continue

            road = _clean(detail.get("road"))
            section = _clean(detail.get("section"))
            direction = _clean(detail.get("direction"))

            if not road:
                continue

            key = (road.lower(), section.lower(), direction.lower())
            if key in seen:
                continue

            seen.add(key)
            result.append(
                {
                    "road": road,
                    "section": section,
                    "direction": direction,
                }
            )

        if result:
            return result

    # Compatibilidad con la estructura anterior.
    roads = [
        _clean(value)
        for value in _clean(item.get("road")).split(",")
        if _clean(value)
    ]

    section = _clean(item.get("section"))

    return [
        {
            "road": road,
            "section": section,
            "direction": _clean(item.get("direction")),
        }
        for road in roads
    ]


def _format_road_line(detail):
    road = _escape(detail.get("road"))
    section = _escape(detail.get("section"))

    if not road:
        return ""

    if section:
        return f"• <b>{road}</b> — <i>{section}</i>"

    return f"• <b>{road}</b>"


def _official_sources(item):
    raw = item.get("other_sources")

    if isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = re.split(r"\s*\|\s*", _clean(raw))

    sources = []
    seen = set()

    for value in values:
        value = _clean(value)
        if not value:
            continue

        if value in seen:
            continue

        seen.add(value)
        sources.append(value)

    return sources


def incident_key(item):
    """
    Identidad estable del incendio.

    No utiliza el titular/nombre textual del incendio porque INFOCA puede
    publicar el mismo incendio con titulares diferentes. Provincia +
    municipio evita avisos duplicados por cambios de titular.
    """
    return "|".join(
        [
            _clean(item.get("province")).strip().lower(),
            _clean(item.get("municipality")).strip().lower(),
        ]
    )


def format_new_incident(item):
    lines = [
        "<b>🔥 CORTE DE CARRETERA POR INCENDIO</b>",
        "",
        f"<i>{_escape(item.get('fire', 'Incendio forestal'))}</i>",
        f"📍 {_escape(item.get('municipality', 'No disponible'))}"
        f" ({_escape(item.get('province', 'No disponible'))})",
        "",
        "<b>🚧 CARRETERAS AFECTADAS</b>",
    ]

    for detail in _road_details(item):
        line = _format_road_line(detail)
        if line:
            lines.append(line)

    if len(lines) == 6:
        # No debería ocurrir en una incidencia válida, pero evita dejar
        # un encabezado vacío si los datos llegan incompletos.
        lines.pop()

    lines.extend(
        [
            "",
            f"🕐 Detectado: "
            f"{_escape(_format_detected_at(item.get('detected_at')))}",
            f"<b>DGT:</b> <i>{_escape(item.get('dgt') or 'No')}</i>",
            f"<b>INFOCA:</b> <i>{_escape(item.get('infoca') or 'No')}</i>",
        ]
    )

    sources = _official_sources(item)

    if sources:
        lines.extend(
            [
                "",
                "Fuentes oficiales:",
            ]
        )

        for source in sources:
            escaped = _escape(source)

            if re.match(r"^https?://", source, re.IGNORECASE):
                lines.append(
                    f"• <a href=\"{escaped}\">{escaped}</a>"
                )
            else:
                lines.append(
                    f"• {escaped}"
                )

    lines.extend(
        [
            "",
            "¿Ya lo has atendido?",
        ]
    )

    return "\n".join(lines)


def format_reopening(item):
    lines = [
        "<b>🔓 CARRETERA REABIERTA</b>",
        "",
        f"<i>{_escape(item.get('fire', 'Incendio forestal'))}</i>",
        f"📍 {_escape(item.get('municipality', 'No disponible'))}"
        f" ({_escape(item.get('province', 'No disponible'))})",
        "",
    ]

    road = _escape(item.get("road"))
    section = _escape(item.get("section"))

    if road:
        if section:
            lines.append(
                f"🚧 <b>{road}</b> — <i>{section}</i>"
            )
        else:
            lines.append(
                f"🚧 <b>{road}</b>"
            )

    reopened_at = _format_detected_at(
        item.get("reopened_at")
    )

    lines.extend(
        [
            "",
            f"🕐 Reabierta: {_escape(reopened_at)}",
            "Situación: <b>Reapertura confirmada</b>",
        ]
    )

    source = _clean(item.get("source"))

    if source:
        lines.extend(
            [
                "Fuente oficial:",
                f"• <a href=\"{_escape(source)}\">"
                f"{_escape(source)}</a>",
            ]
        )

    return "\n".join(lines)


def _merge_incident_items(items):
    """
    Fusiona varias detecciones del mismo incendio antes de decidir si se
    envía el aviso. Así, aunque INFOCA entregue varias actualizaciones en
    la misma ejecución, Telegram recibe una sola fotografía completa.
    """
    if not items:
        return None

    base = dict(items[0])

    merged_details = []
    seen_details = set()

    for item in items:
        for detail in _road_details(item):
            road = _clean(detail.get("road"))
            section = _clean(detail.get("section"))
            direction = _clean(detail.get("direction"))

            if not road:
                continue

            key = (
                road.lower(),
                section.lower(),
                direction.lower(),
            )

            if key in seen_details:
                continue

            seen_details.add(key)
            merged_details.append(
                {
                    "road": road,
                    "section": section,
                    "direction": direction,
                }
            )

        # Conserva todas las fuentes oficiales.
        existing_sources = _official_sources(base)
        for source in _official_sources(item):
            if source not in existing_sources:
                existing_sources.append(source)

        base["other_sources"] = " | ".join(existing_sources)

        # Preferimos un valor real frente a uno vacío.
        for field in (
            "fire",
            "province",
            "municipality",
            "detected_at",
            "dgt",
            "infoca",
            "source_url",
            "source_title",
        ):
            value = item.get(field)
            if value not in ("", None, "No disponible"):
                if base.get(field) in (
                    "",
                    None,
                    "No disponible",
                ):
                    base[field] = value

    base["road_details"] = merged_details
    base["road"] = ", ".join(
        detail["road"]
        for detail in merged_details
    )

    return base


def process_incidents(state, detected):
    alerts = []
    incidents = state.setdefault("incidents", {})

    # Agrupar primero. Esto evita que dos artículos del mismo incendio
    # produzcan dos mensajes separados dentro de la misma ejecución.
    batches = {}

    for item in detected:
        key = incident_key(item)
        batches.setdefault(key, []).append(item)

    for key, items in batches.items():
        merged = _merge_incident_items(items)
        if not merged:
            continue

        if key not in incidents:
            incidents[key] = {
                **merged,
                "status": "PENDIENTE",
                "notified": True,
                "reopened_notified": False,
            }

            alerts.append(
                format_new_incident(merged)
            )

        else:
            current = incidents[key]

            # Actualiza la fotografía actual completa del incendio.
            for field, value in merged.items():
                if value in ("", None):
                    continue

                current[field] = value

    return alerts


def _reopening_key(item):
    return "|".join(
        [
            _clean(item.get("fire")).lower(),
            _clean(item.get("province")).lower(),
            _clean(item.get("municipality")).lower(),
            _clean(item.get("road")).lower(),
            _clean(item.get("section")).lower(),
        ]
    )


def process_reopenings(state, reopenings):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in reopenings:
        # Busca el incendio existente sin depender de la carretera,
        # porque el aviso activo puede contener varias.
        fire = _clean(item.get("fire")).lower()
        province = _clean(item.get("province")).lower()
        municipality = _clean(item.get("municipality")).lower()

        matching_key = None

        for key, current in incidents.items():
            if (
                _clean(current.get("fire")).lower() == fire
                and _clean(current.get("province")).lower() == province
                and _clean(current.get("municipality")).lower() == municipality
            ):
                matching_key = key
                break

        if matching_key is None:
            continue

        current = incidents[matching_key]

        road = _clean(item.get("road"))
        active_roads = {
            _clean(detail.get("road")).lower()
            for detail in _road_details(current)
        }

        # Nunca notificamos una reapertura de una carretera que todavía
        # figura como activa en el estado almacenado.
        if road and road.lower() in active_roads:
            continue

        reopen_key = _reopening_key(item)

        if current.get("last_reopening_key") == reopen_key:
            continue

        current["last_reopening_key"] = reopen_key
        current["road_open"] = True

        alerts.append(
            format_reopening(item)
        )

    return alerts
