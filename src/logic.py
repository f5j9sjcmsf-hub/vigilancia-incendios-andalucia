import datetime as _datetime
import html
import re


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _escape(value):
    return html.escape(_clean(value), quote=True)


def _format_detected_at(value):
    value = _clean(value)
    if not value:
        return "No disponible"

    if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", value):
        return value

    try:
        parsed = _datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value[:16]


def _road_details(item):
    details = item.get("road_details")
    result = []
    seen = set()

    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            road = _clean(detail.get("road"))
            section = _clean(detail.get("section"))
            direction = _clean(detail.get("direction"))
            key = (road.lower(), section.lower(), direction.lower())
            if not road or key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "road": road,
                    "section": section,
                    "direction": direction,
                    "datex_ids": list(detail.get("datex_ids", [])),
                    "situation_ids": list(detail.get("situation_ids", [])),
                }
            )

    if result:
        return result

    section = _clean(item.get("section"))
    direction = _clean(item.get("direction"))
    return [
        {"road": road, "section": section, "direction": direction}
        for road in (_clean(value) for value in _clean(item.get("road")).split(","))
        if road
    ]


def _road_names(item):
    return {
        _clean(detail.get("road")).lower()
        for detail in _road_details(item)
        if _clean(detail.get("road"))
    }


def _situation_ids(item):
    values = item.get("situation_ids", [])
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return {_clean(value) for value in values if _clean(value)}


def incident_key(item):
    identity = _clean(item.get("incident_id"))
    if identity:
        return identity.lower()

    situations = sorted(_situation_ids(item))
    if situations:
        return "dgt:" + "|".join(situations).lower()

    return "legacy:" + "|".join(
        [
            _clean(item.get("fire")).lower(),
            _clean(item.get("province")).lower(),
            _clean(item.get("municipality")).lower(),
        ]
    )


def _format_location(item):
    municipality = _clean(item.get("municipality")) or "No disponible"
    province = _clean(item.get("province")) or "No disponible"
    return f"📍 {_escape(municipality)} ({_escape(province)})"


def _format_road_line(detail):
    road = _escape(detail.get("road"))
    section = _clean(detail.get("section"))
    if not road:
        return ""
    if section:
        section = re.sub(r"^PK\s*", "", section, flags=re.IGNORECASE)
        section = re.sub(r"\s*[-‐‑‒–—]\s*", " – ", section)
        return f"• <b>{road}</b>\n<i>Pk {_escape(section)}</i>"
    return f"• <b>{road}</b>"


def _confirmation_lines(item):
    lines = ["<b>INFOCAR/DGT:</b> <i>Confirmado</i>"]
    if item.get("infoca_matched"):
        lines.append("<b>INFOCA:</b> <i>Incendio identificado</i>")
    return lines


def format_new_incident(item):
    lines = [
        "<b>🔥 CORTE DE CARRETERA POR INCENDIO</b>",
        "",
        f"<i>{_escape(item.get('fire') or 'Incendio forestal')}</i>",
        _format_location(item),
        "",
        "<b>🔴 CARRETERAS CORTADAS</b>",
        "",
    ]

    for detail in _road_details(item):
        line = _format_road_line(detail)
        if line:
            lines.append(line)

    lines.extend(
        [
            "",
            f"🕐 Detectado: {_escape(_format_detected_at(item.get('detected_at')))}",
            *_confirmation_lines(item),
        ]
    )
    return "\n".join(lines)


def format_incident_update(item):
    lines = [
        "<b>🔄 ACTUALIZACIÓN DE CORTE POR INCENDIO</b>",
        "",
        f"<i>{_escape(item.get('fire') or 'Incendio forestal')}</i>",
        _format_location(item),
        "",
        "<b>🔴 CARRETERAS CORTADAS</b>",
        "",
    ]

    for detail in _road_details(item):
        line = _format_road_line(detail)
        if line:
            lines.append(line)

    lines.extend(
        [
            "",
            f"🕐 Detectado: {_escape(_format_detected_at(item.get('detected_at')))}",
            *_confirmation_lines(item),
        ]
    )
    return "\n".join(lines)


def format_reopening(item):
    road_line = _format_road_line(item)

    return "\n".join(
        [
            "<b>🟢 CARRETERA REABIERTA</b>",
            "",
            f"<i>{_escape(item.get('fire') or 'Incendio forestal')}</i>",
            _format_location(item),
            "",
            road_line,
            "",
            f"🕐 Reabierta: {_escape(_format_detected_at(item.get('reopened_at')))}",
            "<b>INFOCAR/DGT:</b> <i>Confirmado</i>",
        ]
    )


def _matching_incident_keys(incidents, item):
    target = incident_key(item)
    matches = []
    if target in incidents:
        matches.append(target)

    situations = _situation_ids(item)
    if situations:
        for key, current in incidents.items():
            if key not in matches and situations.intersection(_situation_ids(current)):
                matches.append(key)

    # Compatibilidad con estados anteriores a la identidad DATEX estable.
    if not matches:
        legacy = "|".join(
            [
                _clean(item.get("fire")).lower(),
                _clean(item.get("province")).lower(),
                _clean(item.get("municipality")).lower(),
            ]
        )
        for key, current in incidents.items():
            current_legacy = "|".join(
                [
                    _clean(current.get("fire")).lower(),
                    _clean(current.get("province")).lower(),
                    _clean(current.get("municipality")).lower(),
                ]
            )
            if legacy == current_legacy:
                matches.append(key)
                break

    return matches


def _detail_for_road(item, road):
    target = _clean(road).lower()
    for detail in _road_details(item):
        if _clean(detail.get("road")).lower() == target:
            return detail
    return {"road": road, "section": "", "direction": ""}


def process_incidents(state, detected):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in detected or []:
        target_key = incident_key(item)
        matches = _matching_incident_keys(incidents, item)
        current_roads = _road_names(item)

        if not matches:
            incidents[target_key] = {
                **item,
                "status": "ACTIVO",
                "notified": True,
                "reopened_roads": [],
                "road_open": False,
            }
            alerts.append(format_new_incident(item))
            continue

        primary_key = target_key if target_key in matches else matches[0]
        current = dict(incidents[primary_key])
        previous_roads = set()
        previous_details = {}
        reopened_roads = set()
        merged_details = {}
        merged_situations = set()

        for key in matches:
            previous_roads.update(_road_names(incidents[key]))
            merged_situations.update(_situation_ids(incidents[key]))
            for detail in _road_details(incidents[key]):
                road_key = _clean(detail.get("road")).lower()
                merged_details[road_key] = detail
                previous_details[road_key] = detail
            reopened_roads.update(
                _clean(value).lower()
                for value in incidents[key].get("reopened_roads", [])
                if _clean(value)
            )

        for key in matches:
            if key != primary_key:
                incidents.pop(key, None)

        effective_item = dict(item)
        if _clean(item.get("fire")).lower() in ("", "incendio forestal"):
            effective_item["fire"] = current.get("fire", "Incendio forestal")
        for field in ("province", "municipality"):
            if _clean(item.get(field)).lower() in ("", "no disponible"):
                effective_item[field] = current.get(field, "No disponible")

        added_roads = current_roads.difference(previous_roads)
        changed_roads = set()
        incoming_details = {
            _clean(detail.get("road")).lower(): detail
            for detail in _road_details(item)
        }
        # Una migración que fusiona varias claves históricas no es una
        # actualización operativa y no debe generar un aviso retrospectivo.
        if len(matches) == 1:
            for road in current_roads.intersection(previous_roads):
                previous = previous_details.get(road, {})
                incoming = incoming_details.get(road, {})
                previous_signature = (
                    _clean(previous.get("section")).lower(),
                    _clean(previous.get("direction")).lower(),
                )
                incoming_signature = (
                    _clean(incoming.get("section")).lower(),
                    _clean(incoming.get("direction")).lower(),
                )
                if previous_signature != incoming_signature:
                    changed_roads.add(road)

        updated_roads = added_roads.union(changed_roads)
        if updated_roads:
            details = [
                _detail_for_road(item, road)
                for road in sorted(updated_roads)
            ]
            alert_item = {
                **effective_item,
                "road_details": details,
                "road": ", ".join(detail["road"] for detail in details),
            }
            alerts.append(format_incident_update(alert_item))
            reopened_roads.difference_update(added_roads)

        for field, value in item.items():
            if value not in ("", None, "No disponible", "Incendio forestal"):
                current[field] = value

        for detail in _road_details(item):
            merged_details[_clean(detail.get("road")).lower()] = detail
        current["road_details"] = list(merged_details.values())
        current["road"] = ", ".join(
            detail["road"] for detail in current["road_details"]
        )
        merged_situations.update(_situation_ids(item))
        current["situation_ids"] = sorted(merged_situations)
        current["reopened_roads"] = sorted(reopened_roads)
        current["status"] = "ACTIVO"
        current["notified"] = True
        current["road_open"] = False

        if primary_key != target_key and target_key not in incidents:
            incidents.pop(primary_key, None)
            primary_key = target_key
        incidents[primary_key] = current

    return alerts


def process_reopenings(state, reopenings):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in reopenings or []:
        road = _clean(item.get("road"))
        if not road:
            continue

        target_key = _clean(item.get("incident_key")).lower()
        matching_key = target_key if target_key in incidents else None

        if matching_key is None:
            item_situations = _situation_ids(item)
            for key, current in incidents.items():
                if item_situations and item_situations.intersection(_situation_ids(current)):
                    matching_key = key
                    break

        if matching_key is None:
            province = _clean(item.get("province")).lower()
            for key, current in incidents.items():
                if road.lower() not in _road_names(current):
                    continue
                current_province = _clean(current.get("province")).lower()
                if not province or province in current_province:
                    matching_key = key
                    break

        if matching_key is None:
            continue

        current = incidents[matching_key]
        reopened_roads = {
            _clean(value).lower()
            for value in current.get("reopened_roads", [])
            if _clean(value)
        }
        if road.lower() in reopened_roads:
            continue

        reopened_roads.add(road.lower())
        remaining = [
            detail
            for detail in _road_details(current)
            if _clean(detail.get("road")).lower() != road.lower()
        ]
        current["road_details"] = remaining
        current["road"] = ", ".join(detail["road"] for detail in remaining)
        current["reopened_roads"] = sorted(reopened_roads)
        current["status"] = "ACTIVO" if remaining else "REABIERTO"
        current["road_open"] = not remaining
        alerts.append(format_reopening(item))

    return alerts


def initialize_baseline(state, detected):
    incidents = {}
    for item in detected or []:
        key = incident_key(item)
        if not key:
            continue
        incidents[key] = {
            **item,
            "status": "ACTIVO",
            "notified": True,
            "reopened_roads": [],
            "road_open": False,
        }
    state["incidents"] = incidents
    state["monitoring_initialized"] = True
    state["baseline_at"] = _datetime.datetime.now().isoformat()


def format_status(state):
    incidents = state.get("incidents", {})
    active_roads = {
        detail["road"]
        for item in incidents.values()
        if isinstance(item, dict)
        for detail in _road_details(item)
        if detail.get("road")
    }
    lines = [
        "📊 <b>ESTADO DE LA VIGILANCIA</b>",
        "",
        f"Incidentes registrados: <b>{len(incidents)}</b>",
        f"Carreteras cortadas: <b>{len(active_roads)}</b>",
        f"Última ejecución: {_escape(state.get('last_run') or 'No disponible')}",
    ]
    return "\n".join(lines)


def format_snapshot(detected, captured_at=None):
    captured = _format_detected_at(
        captured_at or _datetime.datetime.now().isoformat()
    )
    items = list(detected or [])
    lines = [f"<b>🕐 ACTUALIZACIÓN: {_escape(captured)}</b>", ""]

    if not items:
        lines.append(
            "🟢 <b>No constan carreteras cortadas por incendio en Andalucía.</b>"
        )
        return "\n".join(lines)

    lines.append(f"🚧 <b>Incidentes con carreteras cortadas: {len(items)}</b>")
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                "",
                f"<b>{index}. {_escape(item.get('fire') or 'Incendio forestal')}</b>",
                _format_location(item),
                "<b>🔴 CARRETERAS CORTADAS</b>",
                "",
            ]
        )
        for detail in _road_details(item):
            line = _format_road_line(detail)
            if line:
                lines.append(line)
        lines.extend(
            [
                "",
                f"🕐 Detectado: {_escape(_format_detected_at(item.get('detected_at')))}",
                *_confirmation_lines(item),
            ]
        )

    return "\n".join(lines)
