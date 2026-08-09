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
        "(compatible; VigilanciaIncendiosAndalucia/2.0)"
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


def _datex_km(record):
    """
    SOLO acepta un PK explícito.

    Nunca usa 'from' o 'to' como PK porque en DATEX esos campos
    pueden contener descripciones completas de localización,
    coordenadas, municipio, etc.
    """
    value = _tag_text(
        record,
        (
            "kilometerPoint",
            "kilometrePoint",
            "kilometricPoint",
            "pk",
        ),
    )

    if not value:
        return ""

    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)",
        value,
    )

    if not match:
        return ""

    return f"PK {match.group(1).replace(',', '.')}"


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
    Devuelve SOLO registros DATEX que cumplen:

        forestFire / seriousFire
        +
        roadClosed
        -
        rerouting/diversion

    INFOCAR crea el corte. No se utilizan noticias para crear
    un corte de carretera.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    records = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].lower()
        == "situationrecord"
    ]

    results = []
    seen = set()

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
            or f"{road}|{km}|{lat}|{lon}|{direction}"
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
                r"\s+(?:obliga|provoca|afecta|ha|y)\s+",
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


def fetch_infoca_fires():
    fires = []

    for article in get_candidate_articles():
        item = parse_infoca_article(article)

        if not item:
            continue

        fires.append(item)

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


def _dgt_matches_fire(dgt_item, fire):
    """
    INFOCAR aporta el corte.
    INFOCA aporta el incendio al que pertenece.

    La carretera mencionada en INFOCA se utiliza SOLO para
    asociar el corte, nunca para crear uno.
    """
    road = normalize_road(
        dgt_item.get("road", "")
    )

    province = fire.get(
        "province",
        "No disponible",
    )

    if not _road_belongs_to_province(
        road,
        province,
    ):
        return False

    if road in {
        normalize_road(value)
        for value in fire.get("roads", [])
    }:
        return True

    location = normalize(
        dgt_item.get(
            "location_text",
            "",
        )
    ).lower()

    municipality = normalize(
        fire.get(
            "municipality",
            "",
        )
    ).lower()

    # Si INFOCAR proporciona el municipio y coincide
    # con el incendio de INFOCA, es una asociación válida.
    if (
        municipality
        and municipality != "no disponible"
        and municipality in location
    ):
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


def _merge_dgt_into_fire(fire, dgt_items):
    roads = []

    for item in dgt_items:
        road = normalize_road(
            item.get("road", "")
        )

        if not road:
            continue

        section = normalize(
            item.get("section", "")
        )

        value = road

        if section:
            value = f"{road} — {section}"

        if value not in roads:
            roads.append(value)

    if not roads:
        return None

    # Si la provincia del incendio no está disponible,
    # la inferimos solo de las carreteras provinciales DGT.
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
        "fire_status": (
            "Incendio forestal confirmado "
            "por INFOCA/Junta"
        ),
        "infoca": (
            "Incendio confirmado por "
            "INFOCA/Junta"
        ),
        "dgt": (
            "Corte confirmado por "
            "INFOCAR/DGT"
        ),
        "other_sources": fire.get(
            "source_url",
            "",
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
        matched = [
            item
            for item in dgt_items
            if _dgt_matches_fire(
                item,
                fire,
            )
        ]

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


def fetch_official_reopenings():
    """
    Las desapariciones de INFOCAR NO se consideran reaperturas.

    Solo se devuelven reaperturas expresamente comunicadas por
    una fuente oficial de la Junta/INFOCA.
    """
    reopenings = []

    for article in get_candidate_articles():
        try:
            response = get(article["url"])
        except Exception:
            continue

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
            continue

        if not contains_any(
            full_text,
            REOPEN_KEYWORDS,
        ):
            continue

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

        if not roads:
            continue

        reopenings.append(
            {
                "fire": fire_name,
                "province": province,
                "municipality": municipality,
                "road": ", ".join(roads),
                "section": "",
                "reopened_at": display_datetime(),
                "source": article["url"],
                "source_title": title,
            }
        )

    # Deduplicación sencilla.
    unique = {}

    for item in reopenings:
        key = "|".join(
            (
                normalize(
                    item.get("fire", "")
                ).lower(),
                normalize(
                    item.get("province", "")
                ).lower(),
                normalize(
                    item.get("municipality", "")
                ).lower(),
                normalize(
                    item.get("road", "")
                ).lower(),
            )
        )

        unique[key] = item

    return list(unique.values())
