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
    Un único aviso por incendio.

    No utiliza la lista de carreteras: si el mismo incendio incorpora
    nuevas carreteras en una ejecución posterior, no genera otro aviso.
    """
    return "|".join(
        [
            _clean(item.get("fire")).strip().lower(),
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
            "<b>DGT:</b> <i>Confirmado</i>",
            "<b>INFOCA:</b> <i>Confirmado</i>",
        ]
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


def _road_details_without(details, road):
    """Elimina una carretera concreta de una lista de detalles."""
    target = _clean(road).lower()
    result = []

    for detail in details or []:
        if not isinstance(detail, dict):
            continue

        if _clean(detail.get("road")).lower() == target:
            continue

        result.append(detail)

    return result


def _active_road_names(item):
    return {
        _clean(detail.get("road")).lower()
        for detail in _road_details(item)
        if _clean(detail.get("road"))
    }


def _find_detail(item, road):
    target = _clean(road).lower()

    for detail in _road_details(item):
        if _clean(detail.get("road")).lower() == target:
            return detail

    return {
        "road": road,
        "section": "",
        "direction": "",
    }


def process_incidents(state, detected):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in detected:
        key = incident_key(item)
        current_roads = _active_road_names(item)

        if key not in incidents:
            incidents[key] = {
                **item,
                "status": "PENDIENTE",
                "notified": True,
                "reopened_notified": False,
                "reopened_roads": [],
            }

            alerts.append(
                format_new_incident(item)
            )
            continue

        current = incidents[key]
        reopened_roads = {
            _clean(value).lower()
            for value in current.get("reopened_roads", [])
        }

        # Una carretera que desapareció previamente y vuelve a aparecer
        # representa un NUEVO corte, aunque pertenezca al mismo incendio.
        reclosed = current_roads.intersection(reopened_roads)

        if reclosed:
            detail_items = []
            for road in sorted(reclosed):
                detail_items.append(
                    _find_detail(item, road)
                )

            alert_item = {
                **item,
                "road_details": detail_items,
                "road": ", ".join(
                    detail.get("road", "")
                    for detail in detail_items
                    if detail.get("road")
                ),
            }

            alerts.append(
                format_new_incident(alert_item)
            )

            reopened_roads.difference_update(reclosed)

        # Actualiza la fotografía actual sin acumular carreteras que ya no
        # figuran en INFOCAR.
        for field, value in item.items():
            if value in ("", None):
                continue
            current[field] = value

        if item.get("road_details") is not None:
            current["road_details"] = item["road_details"]

        current["reopened_roads"] = sorted(reopened_roads)

    return alerts


def _reopening_key(item):
    return "|".join(
        [
            _clean(item.get("fire")).lower(),
            _clean(item.get("province")).lower(),
            _clean(item.get("municipality")).lower(),
            _clean(item.get("road")).lower(),
            _clean(item.get("section")).lower(),
            _clean(item.get("reopened_at")).lower(),
        ]
    )


def process_reopenings(state, reopenings):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in reopenings:
        fire = _clean(item.get("fire")).lower()
        province = _clean(item.get("province")).lower()
        municipality = _clean(item.get("municipality")).lower()
        road = _clean(item.get("road"))

        # Para una reapertura, la carretera es el identificador operativo.
        # No exigimos que nombre de incendio o municipio coincidan exactamente,
        # porque INFOCA puede actualizar esos datos entre dos ejecuciones.
        matching_key = None

        # Primera opción: carretera + provincia.
        for key, current in incidents.items():
            current_province = _clean(current.get("province")).lower()
            active_roads = _active_road_names(current)
            if (
                road
                and road.lower() in active_roads
                and (not province or current_province == province)
            ):
                matching_key = key
                break

        # Segunda opción: carretera sin exigir provincia, solo si no hubo
        # coincidencia anterior. Esto permite absorber cambios de agrupación.
        if matching_key is None:
            for key, current in incidents.items():
                active_roads = _active_road_names(current)
                if road and road.lower() in active_roads:
                    matching_key = key
                    break

        if matching_key is None:
            continue

        current = incidents[matching_key]

        if not road:
            continue

        active_roads = _active_road_names(current)

        # La carretera debe haber desaparecido realmente de la fotografía
        # almacenada antes de confirmar la reapertura.
        if road.lower() in active_roads:
            continue

        reopen_key = _reopening_key(item)
        if current.get("last_reopening_key") == reopen_key:
            continue

        reopened_roads = {
            _clean(value).lower()
            for value in current.get("reopened_roads", [])
        }
        reopened_roads.add(road.lower())

        current["reopened_roads"] = sorted(reopened_roads)
        current["last_reopening_key"] = reopen_key
        current["road_open"] = True

        alerts.append(
            format_reopening(item)
        )

    return alerts



# ============================================================
# CONTROL DEL BOT / LÍNEA BASE
# ============================================================

def initialize_baseline(state, detected):
    """
    Reinicia la memoria de vigilancia tomando ``detected`` como fotografía
    inicial. No genera avisos.

    Se utiliza con las órdenes Iniciar/Reiniciar para que los cortes que ya
    existían antes de comenzar la vigilancia no aparezcan como nuevos.
    """
    incidents = {}

    for item in detected or []:
        key = incident_key(item)
        if not key:
            continue

        incidents[key] = {
            **item,
            "status": "BASELINE",
            "notified": True,
            "reopened_notified": False,
            "reopened_roads": [],
        }

    state["incidents"] = incidents
    state["monitoring_initialized"] = True
    state["baseline_at"] = datetime.now().isoformat()


def format_status(state):
    """Genera el resumen que se devuelve mediante el botón Estado."""
    active = state.get("monitoring_active", True)
    initialized = state.get("monitoring_initialized", False)
    incidents = state.get("incidents", {})

    active_roads = set()
    fires = set()

    for item in incidents.values():
        if not isinstance(item, dict):
            continue

        fires.add(_clean(item.get("fire")) or "Incendio forestal")

        details = _road_details(item)
        for detail in details:
            road = _clean(detail.get("road"))
            if road:
                active_roads.add(road)

    last_run = _clean(state.get("last_run")) or "No disponible"
    baseline = _clean(state.get("baseline_at")) or "No disponible"

    estado = "🟢 ACTIVA" if active else "⏸️ PAUSADA"
    inicializada = "Sí" if initialized else "No"

    lines = [
        "📊 <b>ESTADO DE LA VIGILANCIA</b>",
        "",
        f"Estado: <b>{estado}</b>",
        f"Inicializada: {inicializada}",
        f"Incendios registrados: <b>{len(fires)}</b>",
        f"Carreteras registradas: <b>{len(active_roads)}</b>",
        f"Última ejecución: {last_run}",
        f"Línea base: {baseline}",
    ]

    if active_roads:
        lines.extend([
            "",
            "<b>Carreteras registradas:</b>",
        ])
        for road in sorted(active_roads):
            lines.append(f"• {_escape(road)}")

    return "\n".join(lines)


def _snapshot_key(item):
    fire = _clean(item.get("fire")).lower()
    municipality = _clean(item.get("municipality")).lower()
    province = _clean(item.get("province")).lower()

    # Un incendio con nombre concreto es una única entidad aunque afecte
    # a varias provincias.
    if fire and fire != "incendio forestal":
        return f"name|{fire}"

    return f"place|{municipality}|{province}"

def _merge_snapshot_items(items):
    """
    Consolida defensivamente la fotografía antes de mostrarla.

    Las carreteras siguen siendo las que ya vienen de INFOCAR; aquí solo
    evitamos que una variación de metadatos INFOCA produzca dos informes
    visuales del mismo incendio.
    """
    groups = {}

    for item in items or []:
        key = _snapshot_key(item)

        if key not in groups:
            groups[key] = dict(item)

            # IMPORTANT:
            # Preserve the road_details already supplied by sources.py.
            # These details contain the PK extracted from INFOCAR/DGT.
            groups[key]["road_details"] = [
                dict(detail)
                for detail in (item.get("road_details") or [])
                if isinstance(detail, dict)
            ]

            # Compatibility fallback for older item structures that only
            # provided a plain "road" string and a shared "section".
            if not groups[key]["road_details"]:
                groups[key]["road_details"] = _road_details(item)

            groups[key]["road"] = ", ".join(
                detail.get("road", "")
                for detail in groups[key]["road_details"]
                if detail.get("road")
            )

            continue

        current = groups[key]

        for field in (
            "fire",
            "province",
            "municipality",
            "source_url",
            "source_title",
        ):
            current_value = _clean(current.get(field))
            incoming_value = _clean(item.get(field))

            if (
                not current_value
                or current_value.lower() == "no disponible"
                or current_value.lower() == "incendio forestal"
            ) and incoming_value:
                current[field] = item.get(field)

        existing = {
            (
                _clean(detail.get("road")).lower(),
                _clean(detail.get("section")).lower(),
                _clean(detail.get("direction")).lower(),
            )
            for detail in current.get("road_details", [])
            if isinstance(detail, dict)
        }

        for detail in _road_details(item):
            road_name = _clean(detail.get("road"))
            section = _clean(detail.get("section"))
            direction = _clean(detail.get("direction"))

            if not road_name:
                continue

            key_detail = (
                road_name.lower(),
                section.lower(),
                direction.lower(),
            )

            # If the current snapshot has the same road without a PK but
            # the incoming item provides one, replace the incomplete detail.
            replaced = False
            for existing_detail in current["road_details"]:
                if not isinstance(existing_detail, dict):
                    continue

                if (
                    _clean(existing_detail.get("road")).lower()
                    == road_name.lower()
                ):
                    existing_section = _clean(
                        existing_detail.get("section")
                    )

                    if not existing_section and section:
                        existing_detail.update(
                            {
                                "road": road_name,
                                "section": section,
                                "direction": direction,
                            }
                        )
                    replaced = True
                    break

            if replaced:
                continue

            if key_detail in existing:
                continue

            current["road_details"].append(
                {
                    "road": road_name,
                    "section": section,
                    "direction": direction,
                }
            )
            existing.add(key_detail)

        current["road"] = ", ".join(
            detail.get("road", "")
            for detail in current["road_details"]
            if detail.get("road")
        )

    return list(groups.values())


def format_snapshot(detected, captured_at=None):
    """
    Genera la fotografía actual.

    IMPORTANTE:
    Las carreteras que se muestran aquí proceden de INFOCAR/DGT.
    INFOCA solo aporta el nombre/municipio/provincia.
    """
    captured = _format_detected_at(
        captured_at or datetime.now().isoformat()
    )

    items = _merge_snapshot_items(detected)

    lines = [
        "<b>📸 ESTADO ACTUAL — INFOCAR + INFOCA</b>",
        "",
        f"🕐 Actualización: <b>{_escape(captured)}</b>",
        "",
    ]

    if not items:
        lines.extend(
            [
                "🟢 <b>No constan carreteras cortadas por incendio "
                "en la fotografía actual.</b>",
                "",
                "Esta fotografía queda guardada como referencia "
                "para la siguiente comprobación.",
            ]
        )
        return "\n".join(lines)

    lines.append(
        f"🚧 <b>Incendios con carreteras cortadas: {len(items)}</b>"
    )

    for index, item in enumerate(items, start=1):
        fire = _escape(
            item.get("fire") or "Incendio forestal"
        )
        municipality = _escape(
            item.get("municipality") or "No disponible"
        )
        province = _escape(
            item.get("province") or "No disponible"
        )

        lines.extend(
            [
                "",
                f"<b>{index}. {fire}</b>",
                f"📍 {municipality} ({province})",
                "<b>🚧 CARRETERAS AFECTADAS</b>",
            ]
        )

        details = _road_details(item)

        if not details:
            lines.append("• No hay carreteras detalladas.")
            continue

        for detail in details:
            road_line = _format_road_line(detail)
            if road_line:
                lines.append(road_line)

        detected_at = _format_detected_at(
            item.get("detected_at")
        )

        lines.extend(
            [
                "",
                f"🕐 Detectado: {_escape(detected_at)}",
                "<b>DGT:</b> <i>Confirmado</i>",
                "<b>INFOCA:</b> <i>Confirmado</i>",
            ]
        )

    return "\n".join(lines)
