def incident_key(item):
    return "|".join([
        item.get("fire", "").strip().lower(),
        item.get("province", "").strip().lower(),
        item.get("municipality", "").strip().lower(),
        item.get("road", "").strip().lower(),
        item.get("section", "").strip().lower(),
        item.get("direction", "").strip().lower(),
        item.get("closure_type", "").strip().lower(),
    ])

def format_new_incident(item):
    return (
        "🔥 <b>CORTE DE CARRETERA POR INCENDIO</b>\n\n"
        f"<b>Incendio:</b> {item.get('fire', 'No disponible')}\n"
        f"<b>Provincia:</b> {item.get('province', 'No disponible')}\n"
        f"<b>Municipio:</b> {item.get('municipality', 'No disponible')}\n"
        f"<b>Carretera:</b> {item.get('road', 'No disponible')}\n"
        f"<b>Tramo:</b> {item.get('section') or 'No disponible'}\n"
        f"<b>Sentido:</b> {item.get('direction') or 'No disponible'}\n"
        f"<b>Tipo de corte:</b> {item.get('closure_type', 'No disponible')}\n"
        f"<b>Hora detectada:</b> {item.get('detected_at', 'No disponible')}\n"
        f"<b>Situación del incendio:</b> {item.get('fire_status') or 'No disponible'}\n\n"
        f"<b>INFOCA:</b> {item.get('infoca') or 'No disponible'}\n"
        f"<b>DGT:</b> {item.get('dgt') or 'No disponible'}\n"
        f"<b>Otras fuentes oficiales:</b> {item.get('other_sources') or 'No disponible'}\n\n"
        "<b>¿Ya lo has atendido?</b>"
    )

def format_reopening(item):
    return (
        "🔓 <b>CARRETERA REABIERTA</b>\n\n"
        f"<b>Incendio:</b> {item.get('fire', 'No disponible')}\n"
        f"<b>Carretera:</b> {item.get('road', 'No disponible')}\n"
        f"<b>Tramo:</b> {item.get('section') or 'No disponible'}\n"
        f"<b>Municipio:</b> {item.get('municipality', 'No disponible')}\n"
        f"<b>Provincia:</b> {item.get('province', 'No disponible')}\n"
        f"<b>Hora aproximada de reapertura:</b> {item.get('reopened_at', 'No disponible')}\n"
        f"<b>Fuente:</b> {item.get('source', 'No disponible')}"
    )

def process_incidents(state, detected):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in detected:
        key = incident_key(item)
        if key not in incidents:
            incidents[key] = {
                **item,
                "status": "PENDIENTE",
                "notified": True,
                "reopened_notified": False,
            }
            alerts.append(format_new_incident(item))
        else:
            incidents[key].update({k: v for k, v in item.items() if v not in ("", None)})

    return alerts

def process_reopenings(state, reopenings):
    alerts = []
    incidents = state.setdefault("incidents", {})

    for item in reopenings:
        key = incident_key(item)
        if key in incidents and not incidents[key].get("reopened_notified"):
            incidents[key]["road_open"] = True
            incidents[key]["reopened_notified"] = True
            alerts.append(format_reopening(item))

    return alerts
