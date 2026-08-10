import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import ANDALUSIA_PROVINCES


# ============================================================
# CONFIGURACIÓN
# ============================================================

JUNTA_BASE = "https://www.juntadeandalucia.es"
JUNTA_SEARCH_URL = (
    "https://www.juntadeandalucia.es/presidencia/portavoz/"
    "emergencias112"
)

# INFOCAR / DGT DATEX II
DGT_URLS = (
    "https://infocar.dgt.es/datex2/v3/dgt/SituationPublication/incidencias.xml",
    "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; VigilanciaIncendiosAndalucia/3.0)"
    )
}

TIMEOUT = 30

FIRE_KEYWORDS = (
    "incendio forestal",
    "incendio",
    "fuego forestal",
    "plan infoca",
    "infoca",
)

CLOSURE_KEYWORDS = (
    "corte",
    "cortada",
    "cortado",
    "cerrada",
    "cerrado",
    "cierre",
    "interrumpida",
    "interrumpido",
    "sin circulación",
    "sin circulacion",
    "restricción",
    "restriccion",
    "restringido",
    "restringida",
    "prohibida la circulación",
    "prohibido el tráfico",
    "prohibido el trafico",
)

REOPEN_KEYWORDS = (
    "reabierta",
    "reabierto",
    "reapertura",
    "abierta al tráfico",
    "abierta al trafico",
    "abierto al tráfico",
    "abierto al trafico",
    "restablecida la circulación",
    "restablecida la circulacion",
    "restablecido el tráfico",
    "restablecido el trafico",
)

# Prefijos inequívocos de carreteras provinciales andaluzas.
ROAD_PROVINCES = {
    "AL": "Almería",
    "CA": "Cádiz",
    "CO": "Córdoba",
    "GR": "Granada",
    "H": "Huelva",
    "HU": "Huelva",
    "J": "Jaén",
    "JA": "Jaén",
    "MA": "Málaga",
    "SE": "Sevilla",
}


# ============================================================
# HTTP
# ============================================================

def get(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response


# ============================================================
# UTILIDADES
# ============================================================

def normalize(text):
    if not text:
        return ""
    return re.sub(
        r"\s+",
        " ",
        str(text).replace("\xa0", " "),
    ).strip()


def contains_any(text, keywords):
    text = normalize(text).lower()
    return any(keyword.lower() in text for keyword in keywords)


def local_now():
    return datetime.now(timezone.utc).astimezone()


def display_datetime():
    return local_now().strftime("%d/%m/%Y %H:%M")


def normalize_road(value):
    value = normalize(value).upper()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"^([A-Z]{1,3})[- ]?(\d{1,5})$", r"\1-\2", value)
    return value


# ============================================================
# INFOCAR / DGT DATEX II
# ============================================================

def _tag_text(element, names):
    """Busca el primer texto no vacío entre varios nombres de tag."""
    if element is None:
        return ""

    for name in names:
        # DATEX puede venir con namespace o sin él.
        for child in element.iter():
            local = child.tag.rsplit("}", 1)[-1]
            if local.lower() == name.lower():
                value = normalize(child.text)
                if value:
                    return value

    return ""


def _record_is_fire(record):
    raw = ET.tostring(
        record,
        encoding="unicode",
    ).lower()

    return (
        "forestfire" in raw
        or "seriousfire" in raw
    )


def _record_is_road_closed(record):
    raw = ET.tostring(
        record,
        encoding="unicode",
    ).lower()

    return (
        "roadclosed" in raw
        or "road closed" in raw
    )


def _record_is_rerouting(record):
    raw = ET.tostring(
        record,
        encoding="unicode",
    ).lower()

    return any(
        value in raw
        for value in (
            "reroutingmanagement",
            "alternate",
            "itinerary",
            "diversion",
            "desvio",
            "desvío",
            "alternateroadorcarriagewayorlaneslayout",
        )
    )


def _record_type(record):
    for key, value in record.attrib.items():
        if key.rsplit("}", 1)[-1].lower() == "type":
            return normalize(value)
    return ""


def _datex_road(record):
    return normalize_road(
        _tag_text(
            record,
            (
                "roadName",
                "roadNumber",
                "roadIdentifier",
            ),
        )
    )


def _clean_km(value):
    """Extrae un PK solo cuando el texto parece realmente kilométrico."""
    value = normalize(value)
    if not value:
        return ""

    # Evita coordenadas, nombres de municipios y descripciones de localización.
    if not re.search(r"\b(?:pk|p\.k\.|km|kil[oó]metro|kil[oó]metros?)\b", value, re.IGNORECASE):
        # Un valor puramente numérico puede ser un PK DATEX válido.
        if not re.fullmatch(r"\d+(?:[.,]\d+)?", value):
            return ""

    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)", value)
    if not match:
        return ""

    return match.group(1).replace(",", ".")


def _datex_km_range(record):
    """Devuelve (desde, hasta) sin usar descripciones de localización como PK."""
    point = _tag_text(record, (
        "kilometerPoint", "kilometrePoint", "kilometricPoint", "pk"
    ))
    if point:
        value = _clean_km(point)
        if value:
            return value, ""

    from_km = _tag_text(record, (
        "fromKilometerPoint", "fromKilometrePoint", "fromKilometricPoint",
        "startKilometerPoint", "startKilometrePoint", "startKm", "fromPk",
    ))
    to_km = _tag_text(record, (
        "toKilometerPoint", "toKilometrePoint", "toKilometricPoint",
        "endKilometerPoint", "endKilometrePoint", "endKm", "toPk",
    ))

    # Algunos DATEX usan from/to, pero solo los aceptamos si contienen
    # explícitamente PK/km o son números puros.
    if not from_km:
        raw = _tag_text(record, ("from",))
        if re.fullmatch(r"\s*(?:PK\s*)?\d+(?:[.,]\d+)?\s*", raw, re.IGNORECASE):
            from_km = raw

    if not to_km:
        raw = _tag_text(record, ("to",))
        if re.fullmatch(r"\s*(?:PK\s*)?\d+(?:[.,]\d+)?\s*", raw, re.IGNORECASE):
            to_km = raw

    return _clean_km(from_km), _clean_km(to_km)


def _format_km_range(record):
    start_km, end_km = _datex_km_range(record)
    if start_km and end_km and start_km != end_km:
        return f"PK {start_km}–{end_km}"
    if start_km:
        return f"PK {start_km}"
    if end_km:
        return f"PK {end_km}"
    return ""


def _datex_km(record):
    return _format_km_range(record)

def _datex_direction(record):
    return _tag_text(
        record,
        (
            "direction",
            "directionalFlow",
            "carriageway",
            "affectedCarriageway",
        ),
    )


def _datex_location_text(record):
    """
    Obtiene texto de localización sin utilizarlo como PK.
    Sirve para cotejar el aviso DGT con INFOCA.
    """
    values = []

    for name in (
        "municipality",
        "municipalityName",
        "localityName",
        "townName",
        "administrativeAreaName",
        "roadName",
        "from",
        "to",
        "descriptor",
    ):
        value = _tag_text(record, (name,))
        if value and value not in values:
            values.append(value)

    return normalize(" ".join(values))


def _datex_coordinates(record):
    lat = ""
    lon = ""

    for element in record.iter():
        local = element.tag.rsplit("}", 1)[-1].lower()

        if local == "latitude" and not lat:
            lat = normalize(element.text)

        if local == "longitude" and not lon:
            lon = normalize(element.text)

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None, None

    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return None, None

    return lat_f, lon_f


def _datex_record_id(record):
    for key in (
        "id",
        "recordId",
        "situationRecordId",
    ):
        value = _tag_text(record, (key,))
        if value:
            return value

    for key, value in record.attrib.items():
        if key.rsplit("}", 1)[-1].lower() in (
            "id",
            "recordid",
        ):
            if normalize(value):
                return normalize(value)

    return ""


def parse_datex_xml(xml_text, source_url):
    """
    Extrae los cortes INFOCAR/DGT y conserva el identificador de la
    ``situation`` DATEX a la que pertenece cada registro.

    Esto es importante porque una misma emergencia puede contener varios
    ``situationRecord`` (A-493, HU-3106, HU-4103, etc.). Si uno de ellos
    puede vincularse al incendio INFOCA, debemos poder recuperar los demás
    registros de ESA MISMA situation, aunque sus localidades sean distintas.

    INFOCAR sigue siendo la autoridad para declarar que existe un corte.
    INFOCA/Junta se utiliza para identificar el incendio al que pertenece.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # DATEX II normalmente organiza los situationRecord dentro de
    # <situation>. Conservamos esa relación en lugar de aplanarla.
    situations = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].lower() == "situation"
    ]

    # Fallback por si una publicación concreta no utiliza el contenedor
    # situation de la forma esperada.
    if not situations:
        situations = [root]

    results = []
    seen = set()

    for situation_index, situation in enumerate(situations):
        # IMPORTANTE: _tag_text() recorre descendientes y podría devolver el
        # id de un situationRecord hijo. Para identificar la situation hay
        # que mirar primero sus atributos y sus hijos directos.
        situation_id = ""

        for key, value in situation.attrib.items():
            local = key.rsplit("}", 1)[-1].lower()
            if local in ("id", "situationid", "situationnumber"):
                if normalize(value):
                    situation_id = normalize(value)
                    break

        if not situation_id:
            for child in list(situation):
                local = child.tag.rsplit("}", 1)[-1].lower()
                if local in ("id", "situationid", "situationnumber"):
                    value = normalize(child.text)
                    if value:
                        situation_id = value
                        break

        if not situation_id:
            situation_id = f"container-{situation_index}"

        records = [
            element
            for element in situation.iter()
            if element.tag.rsplit("}", 1)[-1].lower()
            == "situationrecord"
        ]

        for record in records:
            if not _record_is_fire(record):
                continue

            if not _record_is_road_closed(record):
                continue

            if _record_is_rerouting(record):
                continue

            road = _datex_road(record)
            if not road:
                continue

            km = _datex_km(record)
            direction = _datex_direction(record)
            location_text = _datex_location_text(record)
            lat, lon = _datex_coordinates(record)
            record_id = _datex_record_id(record)

            key = (
                record_id
                or f"{road}|{km}|{lat}|{lon}|{direction}|{situation_id}"
            )

            if key in seen:
                continue

            seen.add(key)

            results.append(
                {
                    "road": road,
                    "section": km or "",
                    "direction": direction or "",
                    "location_text": location_text,
                    "lat": lat,
                    "lon": lon,
                    "datex_id": record_id,
                    "situation_id": situation_id,
                    "dgt_source": source_url,
                    "detected_at": display_datetime(),
                }
            )

    return results


def fetch_datex_closures():
    """
    Consulta las dos publicaciones utilizadas por el script de Waze
    y elimina duplicados entre ambas.
    """
    all_records = []
    seen = set()

    for url in DGT_URLS:
        try:
            response = get(url)
            records = parse_datex_xml(
                response.text,
                url,
            )
        except Exception:
            continue

        for item in records:
            key = (
                item.get("datex_id")
                or (
                    item.get("road"),
                    item.get("section"),
                    item.get("lat"),
                    item.get("lon"),
                    item.get("direction"),
                    item.get("situation_id"),
                )
            )

            if key in seen:
                continue

            seen.add(key)
            all_records.append(item)

    return all_records


# ============================================================
# INFOCA / JUNTA
# ============================================================

def find_province(text):
    text = normalize(text)
    lower = text.lower()

    # Contexto explícito antes que una simple aparición.
    patterns = [
        r"provincia\s+(?:de|del)\s+"
        r"(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|huelva|ja[eé]n|m[aá]laga|sevilla)",
        r"\((almer[ií]a|c[aá]diz|c[oó]rdoba|granada|huelva|ja[eé]n|m[aá]laga|sevilla)\)",
        r"\ben\s+"
        r"(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|huelva|ja[eé]n|m[aá]laga|sevilla)\b",
    ]

    aliases = {
        "almeria": "Almería",
        "almería": "Almería",
        "cádiz": "Cádiz",
        "cadiz": "Cádiz",
        "córdoba": "Córdoba",
        "cordoba": "Córdoba",
        "granada": "Granada",
        "huelva": "Huelva",
        "jaén": "Jaén",
        "jaen": "Jaén",
        "málaga": "Málaga",
        "malaga": "Málaga",
        "sevilla": "Sevilla",
    }

    for pattern in patterns:
        match = re.search(
            pattern,
            lower,
            re.IGNORECASE,
        )
        if match:
            return aliases.get(
                match.group(1).lower(),
                "No disponible",
            )

    # Si solo aparece una provincia en el artículo, es razonable.
    found = []

    for alias, province in aliases.items():
        if re.search(
            rf"\b{re.escape(alias)}\b",
            lower,
        ):
            if province not in found:
                found.append(province)

    if len(found) == 1:
        return found[0]

    return "No disponible"


def extract_roads(text):
    pattern = re.compile(
        r"\b("
        r"A|AP|N|AL|CA|CO|GR|H|HU|J|JA|MA|SE|"
        r"EX|CM|CR|TO"
        r")-?\s*(\d{1,5})\b",
        re.IGNORECASE,
    )

    roads = []

    for match in pattern.finditer(
        text or ""
    ):
        road = (
            f"{match.group(1).upper()}-"
            f"{match.group(2)}"
        )

        if road not in roads:
            roads.append(road)

    return roads


def split_sentences(text):
    text = normalize(text)

    if not text:
        return []

    return [
        normalize(part)
        for part in re.split(
            r"(?<=[.!?;])\s+|(?<=:)\s+",
            text,
        )
        if normalize(part)
    ]


def extract_municipality(title, text):
    patterns = (
        r"incendio\s+(?:forestal\s+)?"
        r"(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:–—-]{1,60})",
        r"fuego\s+(?:forestal\s+)?"
        r"(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:–—-]{1,60})",
    )

    for source in (
        title,
        text[:5000],
    ):
        for pattern in patterns:
            match = re.search(
                pattern,
                source,
                re.IGNORECASE,
            )

            if not match:
                continue

            value = normalize(match.group(1))

            value = re.split(
                r"\s+(?:obliga|provoca|afecta|ha|y|pese\s+a)\s+",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]

            value = value.strip(
                " .,:;–—-"
            )

            if value and len(value) <= 60:
                return value

    return "No disponible"


def extract_fire_name(title, municipality):
    if municipality != "No disponible":
        return f"Incendio de {municipality}"

    title = normalize(title)

    patterns = (
        r"incendio\s+(?:forestal\s+)?"
        r"(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:–—-]{1,60})",
        r"fuego\s+(?:forestal\s+)?"
        r"(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:–—-]{1,60})",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            title,
            re.IGNORECASE,
        )

        if match:
            value = normalize(match.group(1))
            if value:
                return f"Incendio de {value}"

    return "Incendio forestal"


def get_candidate_articles():
    try:
        response = get(JUNTA_SEARCH_URL)
    except Exception:
        return []

    soup = BeautifulSoup(
        response.text,
        "lxml",
    )

    candidates = []

    for link in soup.find_all(
        "a",
        href=True,
    ):
        title = normalize(
            link.get_text(
                " ",
                strip=True,
            )
        )

        href = urljoin(
            JUNTA_BASE,
            link["href"],
        )

        if not title:
            continue

        if not contains_any(
            title,
            FIRE_KEYWORDS,
        ):
            continue

        if "juntadeandalucia.es" not in href:
            continue

        candidates.append(
            {
                "title": title,
                "url": href,
            }
        )

    unique = {}

    for item in candidates:
        unique[item["url"]] = item

    return list(unique.values())


def parse_infoca_article(article):
    try:
        response = get(article["url"])
    except Exception:
        return None

    soup = BeautifulSoup(
        response.text,
        "lxml",
    )

    title = normalize(
        soup.title.get_text()
        if soup.title
        else article["title"]
    )

    body = normalize(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    full_text = f"{title} {body}"

    if not contains_any(
        full_text,
        FIRE_KEYWORDS,
    ):
        return None

    province = find_province(
        full_text
    )

    municipality = extract_municipality(
        title,
        full_text,
    )

    fire_name = extract_fire_name(
        title,
        municipality,
    )

    roads = extract_roads(
        full_text
    )

    return {
        "fire": fire_name,
        "province": province,
        "municipality": municipality,
        "roads": roads,
        "text": full_text,
        "source_url": article["url"],
        "source_title": title,
    }


def _fire_group_key(item):
    """Agrupa actualizaciones del mismo incendio sin perder carreteras."""
    province = normalize(item.get("province", "")).lower()
    municipality = normalize(item.get("municipality", "")).lower()

    if municipality and municipality != "no disponible":
        return f"{province}|{municipality}"

    fire = normalize(item.get("fire", "")).lower()
    return f"{province}|{fire}"


def _merge_infoca_fire_updates(items):
    """Fusiona artículos del mismo incendio y conserva todas sus carreteras."""
    if not items:
        return None

    base = sorted(
        items,
        key=lambda x: (
            x.get("municipality") == "No disponible",
            x.get("fire") == "Incendio forestal",
        ),
    )[0]

    roads = []
    sources = []
    province = base.get("province", "No disponible")
    municipality = base.get("municipality", "No disponible")
    fire_name = base.get("fire", "Incendio forestal")

    for item in items:
        if province == "No disponible" and item.get("province") != "No disponible":
            province = item.get("province")
        if municipality == "No disponible" and item.get("municipality") != "No disponible":
            municipality = item.get("municipality")
        if fire_name == "Incendio forestal" and item.get("fire"):
            fire_name = item.get("fire")

        for road in item.get("roads", []):
            road = normalize_road(road)
            if road and road not in roads:
                roads.append(road)

        source = item.get("source_url", "")
        if source and source not in sources:
            sources.append(source)

    return {
        **base,
        "fire": fire_name,
        "province": province,
        "municipality": municipality,
        "roads": roads,
        "source_urls": sources,
        "source_url": sources[0] if sources else base.get("source_url", ""),
    }


def fetch_infoca_fires():
    """
    Consulta las publicaciones INFOCA/Junta y fusiona las actualizaciones
    que corresponden al mismo incendio. Una actualización posterior que
    mencione solo una carretera no hace desaparecer las anteriores.
    """
    parsed = []

    for article in get_candidate_articles():
        item = parse_infoca_article(article)
        if item:
            parsed.append(item)

    groups = {}
    for item in parsed:
        key = _fire_group_key(item)
        groups.setdefault(key, []).append(item)

    fires = []
    for items in groups.values():
        merged = _merge_infoca_fire_updates(items)
        if merged:
            fires.append(merged)

    return fires


# ============================================================
# VINCULACIÓN INFOCAR ↔ INFOCA
# ============================================================

def _road_belongs_to_province(road, province):
    match = re.match(
        r"^([A-Z]{1,3})-\d{1,5}$",
        normalize_road(road),
    )

    if not match:
        return True

    road_province = ROAD_PROVINCES.get(
        match.group(1)
    )

    return (
        road_province is None
        or province == "No disponible"
        or road_province == province
    )


def _haversine_km(lat1, lon1, lat2, lon2):
    """Distancia aproximada entre dos coordenadas en kilómetros."""
    if None in (lat1, lon1, lat2, lon2):
        return None

    from math import radians, sin, cos, asin, sqrt

    r = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def _direct_dgt_matches_fire(dgt_item, fire):
    road = normalize_road(dgt_item.get("road", ""))
    province = fire.get("province", "No disponible")

    if not _road_belongs_to_province(road, province):
        return False

    fire_roads = {
        normalize_road(value)
        for value in fire.get("roads", [])
        if normalize_road(value)
    }

    if road in fire_roads:
        return True

    location = normalize(dgt_item.get("location_text", "")).lower()
    municipality = normalize(fire.get("municipality", "")).lower()

    return bool(
        municipality
        and municipality != "no disponible"
        and municipality in location
    )


def _expand_fire_dgt_cluster(fire, direct_matches, dgt_items):
    """
    Amplía la relación a otros cortes INFOCAR activos del mismo incendio.

    Se hace de forma conservadora: mismo territorio provincial y proximidad
    geográfica a un corte ya asociado. No basta con que sean carreteras de la
    misma provincia.
    """
    if not direct_matches:
        return []

    selected = list(direct_matches)
    selected_keys = {
        item.get("datex_id") or id(item)
        for item in selected
    }

    # 35 km permite cubrir el entorno de Niebla/Valverde sin convertir toda
    # Huelva en un único incendio. La asociación siempre parte de un corte
    # ya vinculado directamente a INFOCA.
    radius_km = 35.0

    changed = True
    while changed:
        changed = False

        for candidate in dgt_items:
            candidate_key = candidate.get("datex_id") or id(candidate)
            if candidate_key in selected_keys:
                continue

            if not _road_belongs_to_province(
                candidate.get("road", ""),
                fire.get("province", "No disponible"),
            ):
                continue

            for anchor in selected:
                distance = _haversine_km(
                    candidate.get("lat"),
                    candidate.get("lon"),
                    anchor.get("lat"),
                    anchor.get("lon"),
                )

                if distance is not None and distance <= radius_km:
                    selected.append(candidate)
                    selected_keys.add(candidate_key)
                    changed = True
                    break

    return selected


def _dgt_matches_fire(dgt_item, fire, dgt_items=None):
    """Asociación directa entre un corte INFOCAR y un incendio INFOCA."""
    if _direct_dgt_matches_fire(dgt_item, fire):
        return True

    # Mantener la asociación por situation DATEX cuando ya existe un ancla.
    situation_id = normalize(dgt_item.get("situation_id", ""))
    if situation_id and dgt_items:
        for other in dgt_items:
            if other is dgt_item:
                continue
            if normalize(other.get("situation_id", "")) != situation_id:
                continue
            if _direct_dgt_matches_fire(other, fire):
                return True

    return False

def _group_key(fire):
    return (
        normalize(
            fire.get("fire", "")
        ).lower()
        + "|"
        + normalize(
            fire.get("province", "")
        ).lower()
        + "|"
        + normalize(
            fire.get("municipality", "")
        ).lower()
    )


def _parse_section_values(section):
    """
    Extrae los valores numéricos de un campo PK ya normalizado.
    Devuelve una lista de floats. No intenta interpretar coordenadas
    ni textos de localización.
    """
    if not section:
        return []

    values = re.findall(
        r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)",
        str(section),
    )

    result = []
    for value in values:
        try:
            result.append(float(value.replace(",", ".")))
        except ValueError:
            continue

    return result


def _format_pk_value(value):
    """
    Formato limpio para PK: 31.8, 28.77, etc.
    """
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text


def _merge_dgt_road_details(dgt_items):
    """
    Agrupa TODOS los registros INFOCAR de una misma carretera.

    Si INFOCAR entrega dos puntos para una carretera (por ejemplo PK 20.8
    y PK 31.8), no los presenta como dos cortes independientes: los
    representa como un único tramo, PK 20.8–31.8.

    Si solo existe un PK, conserva ese único punto.
    Si no existe PK, no muestra ningún PK.
    """
    grouped = {}

    for item in dgt_items:
        road = normalize_road(item.get("road", ""))
        if not road:
            continue

        key = road
        entry = grouped.setdefault(
            key,
            {
                "road": road,
                "direction": normalize(item.get("direction", "")),
                "pk_values": [],
                "raw_sections": [],
            },
        )

        section = normalize(item.get("section", ""))
        values = _parse_section_values(section)

        if values:
            entry["pk_values"].extend(values)

        if not entry["direction"]:
            entry["direction"] = normalize(
                item.get("direction", "")
            )

    details = []

    for entry in grouped.values():
        values = sorted(
            set(
                round(value, 6)
                for value in entry["pk_values"]
            )
        )

        if len(values) >= 2:
            start = _format_pk_value(values[0])
            end = _format_pk_value(values[-1])
            section = (
                f"PK {start}–{end}"
                if start != end
                else f"PK {start}"
            )
        elif len(values) == 1:
            section = f"PK {_format_pk_value(values[0])}"
        else:
            section = ""

        details.append(
            {
                "road": entry["road"],
                "section": section,
                "direction": entry["direction"],
            }
        )

    return details


def _merge_dgt_into_fire(fire, dgt_items):
    """
    Construye una única fotografía del incendio.

    Todos los registros INFOCAR pertenecientes al incendio se agrupan por
    carretera y los PK de una misma carretera se consolidan en un único
    tramo.
    """
    road_details = _merge_dgt_road_details(dgt_items)

    if not road_details:
        return None

    roads = [
        detail["road"]
        for detail in road_details
    ]

    province = fire.get(
        "province",
        "No disponible",
    )

    if province == "No disponible":
        for item in dgt_items:
            road = normalize_road(
                item.get("road", "")
            )
            match = re.match(
                r"^([A-Z]{1,3})-\d{1,5}$",
                road,
            )
            if match:
                inferred = ROAD_PROVINCES.get(
                    match.group(1)
                )
                if inferred:
                    province = inferred
                    break

    return {
        "fire": fire.get(
            "fire",
            "Incendio forestal",
        ),
        "province": province,
        "municipality": fire.get(
            "municipality",
            "No disponible",
        ),
        "road": ", ".join(roads),
        "road_details": road_details,
        "section": "",
        "direction": "",
        "closure_type": "Total / no especificado",
        "detected_at": min(
            (
                item.get(
                    "detected_at",
                    display_datetime(),
                )
                for item in dgt_items
            ),
            default=display_datetime(),
        ),
        "fire_status": "Corte confirmado",
        "infoca": "Confirmado",
        "dgt": "Confirmado",
        "other_sources": " | ".join(
            fire.get("source_urls", [])
            or [fire.get("source_url", "")]
        ),
        "source_url": fire.get(
            "source_url",
            "",
        ),
        "source_title": fire.get(
            "source_title",
            "",
        ),
        "datex_ids": [
            item.get("datex_id", "")
            for item in dgt_items
            if item.get("datex_id")
        ],
        "situation_ids": sorted(
            {
                item.get("situation_id", "")
                for item in dgt_items
                if item.get("situation_id")
            }
        ),
    }


# ============================================================
# API UTILIZADA POR main.py
# ============================================================

def fetch_official_incidents():
    """
    REGLA PRINCIPAL:

    1. INFOCAR/DGT debe confirmar forestFire + roadClosed.
    2. INFOCA/Junta debe identificar el incendio y asociarlo.
    3. Las noticias NO crean cortes por sí mismas.
    4. Los distintos registros DGT del mismo incendio se agrupan
       en un único aviso.
    """
    dgt_items = fetch_datex_closures()

    if not dgt_items:
        return []

    fires = fetch_infoca_fires()

    if not fires:
        # Seguridad: no alertamos de un corte por incendio
        # si no podemos vincularlo a un incendio INFOCA/Junta.
        return []

    grouped = {}

    for fire in fires:
        direct_matches = [
            item
            for item in dgt_items
            if _dgt_matches_fire(
                item,
                fire,
                dgt_items,
            )
        ]

        matched = _expand_fire_dgt_cluster(
            fire,
            direct_matches,
            dgt_items,
        )

        if not matched:
            continue

        key = _group_key(fire)

        if key not in grouped:
            grouped[key] = {
                "fire": fire,
                "dgt": [],
            }

        existing_ids = {
            item.get("datex_id")
            for item in grouped[key]["dgt"]
            if item.get("datex_id")
        }

        for item in matched:
            item_id = item.get("datex_id")

            if item_id and item_id in existing_ids:
                continue

            grouped[key]["dgt"].append(item)

    incidents = []

    for group in grouped.values():
        item = _merge_dgt_into_fire(
            group["fire"],
            group["dgt"],
        )

        if item:
            incidents.append(item)

    return incidents


def _road_is_active_in_infocar(road, active_dgt):
    """True si INFOCAR sigue mostrando esa carretera como cortada."""
    target = normalize_road(road)
    if not target:
        return False

    return any(
        normalize_road(item.get("road", "")) == target
        for item in active_dgt
    )


def _fetch_datex_closures_with_status():
    """
    Igual que ``fetch_datex_closures()``, pero devuelve además si al menos
    una de las publicaciones DATEX se ha consultado correctamente.

    Esto es imprescindible para las reaperturas: una respuesta vacía por
    un fallo de red NO puede interpretarse como que todas las carreteras
    han reabierto.
    """
    all_records = []
    seen = set()
    successful_sources = 0

    for url in DGT_URLS:
        try:
            response = get(url)
            records = parse_datex_xml(
                response.text,
                url,
            )
            successful_sources += 1
        except Exception:
            continue

        for item in records:
            key = (
                item.get("datex_id")
                or (
                    item.get("road"),
                    item.get("section"),
                    item.get("lat"),
                    item.get("lon"),
                    item.get("direction"),
                    item.get("situation_id"),
                )
            )

            if key in seen:
                continue

            seen.add(key)
            all_records.append(item)

    return all_records, successful_sources > 0


def _previous_active_roads(state):
    """
    Extrae las carreteras que figuraban como activas en la última ejecución
    guardada. Conserva también sus PK para poder informar de la reapertura.
    """
    result = []
    incidents = state.get("incidents", {}) if isinstance(state, dict) else {}

    for current in incidents.values():
        if not isinstance(current, dict):
            continue

        fire = current.get("fire", "Incendio forestal")
        province = current.get("province", "No disponible")
        municipality = current.get("municipality", "No disponible")

        details = current.get("road_details")

        if not isinstance(details, list):
            road_text = current.get("road", "")
            details = [
                {
                    "road": road.strip(),
                    "section": current.get("section", ""),
                    "direction": current.get("direction", ""),
                }
                for road in str(road_text).split(",")
                if road.strip()
            ]

        for detail in details:
            if not isinstance(detail, dict):
                continue

            road = normalize_road(detail.get("road", ""))
            if not road:
                continue

            result.append(
                {
                    "fire": fire,
                    "province": province,
                    "municipality": municipality,
                    "road": road,
                    "section": normalize(detail.get("section", "")),
                    "direction": normalize(detail.get("direction", "")),
                }
            )

    return result


def _current_incident_roads(current_incidents):
    """Devuelve el conjunto de carreteras que siguen activas ahora."""
    roads = set()

    for item in current_incidents or []:
        details = item.get("road_details")

        if isinstance(details, list):
            for detail in details:
                if isinstance(detail, dict):
                    road = normalize_road(detail.get("road", ""))
                    if road:
                        roads.add(road)
            continue

        for value in str(item.get("road", "")).split(","):
            road = normalize_road(value)
            if road:
                roads.add(road)

    return roads


def fetch_official_reopenings(previous_state=None, current_incidents=None):
    """
    Detecta reaperturas mediante la desaparición de una carretera del
    INFOCAR/DGT entre dos ejecuciones consecutivas.

    REGLAS:
      1. INFOCAR/DGT es la fuente de verdad para el estado del corte.
      2. La carretera debe haber estado activa en el estado anterior.
      3. INFOCAR debe haberse consultado correctamente.
      4. Si la carretera sigue apareciendo en INFOCAR, NO hay reapertura.
      5. Si vuelve a aparecer posteriormente, se considera un nuevo corte.
      6. Las noticias de INFOCA/Junta NO crean ni confirman la reapertura.

    No se exige que el incendio completo desaparezca: basta con que una
    carretera concreta deje de aparecer.
    """
    if not isinstance(previous_state, dict):
        return []

    previous_roads = _previous_active_roads(previous_state)
    if not previous_roads:
        return []

    active_dgt, dgt_ok = _fetch_datex_closures_with_status()

    # Si INFOCAR no pudo consultarse, no podemos interpretar una ausencia
    # como reapertura. Esto evita falsos positivos por errores de red.
    if not dgt_ok:
        return []

    active_roads = {
        normalize_road(item.get("road", ""))
        for item in active_dgt
        if normalize_road(item.get("road", ""))
    }

    # current_incidents es la fotografía ya vinculada INFOCAR + INFOCA.
    # Se usa como segunda comprobación para no marcar como reabierta una
    # carretera que sigue presente aunque haya cambiado de agrupación.
    current_roads = _current_incident_roads(current_incidents or [])

    reopenings = []
    seen = set()

    for previous in previous_roads:
        road = normalize_road(previous.get("road", ""))
        if not road:
            continue

        if road in active_roads or road in current_roads:
            continue

        key = (
            normalize(previous.get("fire", "")).lower(),
            normalize(previous.get("province", "")).lower(),
            normalize(previous.get("municipality", "")).lower(),
            road,
        )

        if key in seen:
            continue

        seen.add(key)

        reopenings.append(
            {
                "fire": previous.get("fire", "Incendio forestal"),
                "province": previous.get("province", "No disponible"),
                "municipality": previous.get("municipality", "No disponible"),
                "road": road,
                "section": previous.get("section", ""),
                "direction": previous.get("direction", ""),
                "reopened_at": display_datetime(),
                "source": DGT_URLS[0],
                "source_title": "INFOCAR/DGT DATEX II",
            }
        )

    return reopenings

