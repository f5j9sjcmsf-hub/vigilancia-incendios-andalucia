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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; VigilanciaIncendiosAndalucia/1.0)"
    )
}

TIMEOUT = 30

# DATEX II / INFOCAR-DGT.
# Se prueban ambos endpoints para mantener compatibilidad con la publicación
# antigua de INFOCAR y con la publicación DATEX II del Punto de Acceso Nacional.
DGT_DATEX_URLS = (
    "https://infocar.dgt.es/datex2/v3/dgt/SituationPublication/incidencias.xml",
    "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml",
)

DGT_SOURCE_NAME = "INFOCAR/DGT DATEX II"

# Solo se consideran incidencias de Andalucía.
ANDALUSIA_PROVINCE_CODES = {
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


# Distancia máxima aproximada para buscar una carretera
# alrededor de una expresión de corte/restricción.
CONTEXT_WINDOW = 220


# ============================================================
# PALABRAS CLAVE
# ============================================================

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
    "no se permite la circulación",
    "no se permite la circulacion",
    "permanece cortada",
    "permanece cerrado",
    "permanece cerrada",
    "continúa cortada",
    "continua cortada",
    "continúa cerrado",
    "continua cerrado",
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


# ============================================================
# PETICIONES HTTP
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
        text.replace("\xa0", " "),
    ).strip()


def contains_any(text, keywords):
    text = text.lower()

    return any(
        keyword.lower() in text
        for keyword in keywords
    )


def split_sentences(text):
    """
    Divide el texto en bloques razonables para analizar
    el contexto de cada corte.
    """

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


def find_province(text):
    """
    Detecta la provincia de forma contextual.

    No devuelve simplemente la primera provincia que aparece en una noticia,
    porque un artículo puede mencionar otras provincias sin que el incendio
    esté allí.
    """

    if not text:
        return "No disponible"

    text_normalized = normalize(text)
    lower = text_normalized.lower()

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

    # 1. Contexto explícito.
    patterns = [
        r"provincia\s+(?:de|del)\s+(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|huelva|ja[eé]n|m[aá]laga|sevilla)",
        r"en\s+(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|huelva|ja[eé]n|m[aá]laga|sevilla)",
        r"\((almer[ií]a|c[aá]diz|c[oó]rdoba|granada|huelva|ja[eé]n|m[aá]laga|sevilla)\)",
    ]

    for pattern in patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            return aliases[match.group(1).lower()]

    # 2. Prefijo provincial inequívoco de carretera.
    road_province = {
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

    for match in re.finditer(
        r"\b(AL|CA|CO|GR|H|HU|J|JA|MA|SE)-\s*\d{1,5}\b",
        text_normalized,
        re.IGNORECASE,
    ):
        prefix = match.group(1).upper()
        return road_province[prefix]

    # 3. Solo si aparece una única provincia en todo el texto.
    found = []
    for alias, province in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            if province not in found:
                found.append(province)

    if len(found) == 1:
        return found[0]

    return "No disponible"


# ============================================================
# CARRETERAS
# ============================================================

def extract_roads(text):
    """
    Extrae identificadores de carreteras.

    Ejemplos válidos:

        A-49
        A-493
        N-435
        HU-3106
        MA-20
        GR-30
        AP-4

    No acepta números sueltos como:

        112
        2026
        300
        061
    """

    if not text:
        return []

    pattern = re.compile(
        r"\b("
        r"A|AP|N|"
        r"AL|CA|CO|GR|H|HU|J|JA|MA|SE|"
        r"EX|"
        r"CM|CR|TO"
        r")-?\s*(\d{1,5})\b",
        re.IGNORECASE,
    )

    roads = []

    for match in pattern.finditer(text):

        prefix = match.group(1).upper()
        number = match.group(2)

        if not prefix or not number:
            continue

        road = f"{prefix}-{number}"

        if road not in roads:
            roads.append(road)

    return roads


def extract_roads_near_closure(text):
    """
    Solo devuelve carreteras que aparecen en un contexto
    de corte, restricción o reapertura.

    Esto evita convertir una noticia general sobre un incendio
    en un falso corte de carretera.
    """

    sentences = split_sentences(text)

    roads = []

    for sentence in sentences:

        lower = sentence.lower()

        if not contains_any(
            lower,
            CLOSURE_KEYWORDS + REOPEN_KEYWORDS,
        ):
            continue

        sentence_roads = extract_roads(sentence)

        for road in sentence_roads:

            if road not in roads:
                roads.append(road)

    # Segunda pasada para páginas con párrafos muy largos.
    if not roads:

        lower_text = text.lower()

        for keyword in CLOSURE_KEYWORDS + REOPEN_KEYWORDS:

            start = 0

            while True:

                position = lower_text.find(
                    keyword.lower(),
                    start,
                )

                if position == -1:
                    break

                begin = max(
                    0,
                    position - CONTEXT_WINDOW,
                )

                end = min(
                    len(text),
                    position + len(keyword)
                    + CONTEXT_WINDOW,
                )

                context = text[begin:end]

                for road in extract_roads(context):

                    if road not in roads:
                        roads.append(road)

                start = position + len(keyword)

    return roads


# ============================================================
# TRAMOS
# ============================================================

def extract_section(text):

    patterns = [

        r"(?:entre|del)\s+(?:los\s+)?(?:PK|puntos kilométricos?)\s*"
        r"(\d+(?:[.,]\d+)?)\s*(?:y|al)\s*(\d+(?:[.,]\d+)?)",

        r"(?:entre|del)\s+(?:los\s+)?kilómetros?\s*"
        r"(\d+(?:[.,]\d+)?)\s*(?:y|al)\s*(\d+(?:[.,]\d+)?)",

        r"kilómetro\s+(\d+(?:[.,]\d+)?)",

        r"kilometro\s+(\d+(?:[.,]\d+)?)",

        r"\bkm\s+(\d+(?:[.,]\d+)?)",

        r"\bPK\s+(\d+(?:[.,]\d+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        values = [
            value.replace(",", ".")
            for value in match.groups()
            if value
        ]

        if len(values) == 2:
            return f"PK {values[0]}–{values[1]}"

        if len(values) == 1:
            return f"PK {values[0]}"

    return "No disponible"


# ============================================================
# SENTIDO
# ============================================================

def extract_direction(text):

    directions = (
        "sentido Cádiz",
        "sentido Sevilla",
        "sentido Málaga",
        "sentido Granada",
        "sentido Almería",
        "sentido Huelva",
        "sentido Jaén",
        "sentido Córdoba",
        "sentido Madrid",
        "sentido Valencia",
        "sentido Murcia",
        "sentido Algeciras",
        "sentido ambos sentidos",
        "ambos sentidos",
    )

    for direction in directions:

        if direction.lower() in text.lower():

            if direction.lower() == "ambos sentidos":
                return "Ambos sentidos"

            return direction

    return "No disponible"


# ============================================================
# MUNICIPIO
# ============================================================

def clean_place(value):

    value = normalize(value)

    value = re.split(
        r"\s+-\s+"
        r"|\s+—\s+"
        r"|,\s+"
        r"|;\s+"
        r"|\s+uno de\s+"
        r"|\s+pese a\s+"
        r"|\s+por\s+"
        r"|\s+que\s+"
        r"|\s+y\s+",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    return value.strip(
        " .,:;–—-"
    )


def extract_municipality(title, text):

    patterns = (

        r"incendio\s+(?:forestal\s+)?"
        r"(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:–—-]{1,60})",

        r"incendio\s+forestal\s+de\s+"
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

            value = clean_place(
                match.group(1)
            )

            if value and len(value) <= 60:
                return value

    return "No disponible"


# ============================================================
# NOMBRE DEL INCENDIO
# ============================================================

def extract_fire_name(
    title,
    municipality,
):
    """
    Nunca utiliza un titular periodístico completo
    como nombre del incendio.
    """

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

        if not match:
            continue

        value = clean_place(
            match.group(1)
        )

        if value:
            return f"Incendio de {value}"

    return "Incendio forestal"



# ============================================================
# INFOCAR / DGT - DATEX II
# ============================================================

def _local_name(tag):
    """Devuelve el nombre local de un elemento XML ignorando namespaces."""
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1].lower()


def _xml_text(element):
    if element is None:
        return ""
    return normalize(" ".join(element.itertext()))


def _find_descendants(element, names):
    wanted = {name.lower() for name in names}
    return [
        node
        for node in element.iter()
        if _local_name(node.tag) in wanted
    ]


def _first_text(element, names):
    for node in _find_descendants(element, names):
        value = _xml_text(node)
        if value:
            return value
    return ""


def _record_xml_text(record):
    return normalize(
        " ".join(
            node.text or ""
            for node in record.iter()
            if node.text
        )
    ).lower()


def _datex_is_forest_fire(record):
    """
    INFOCAR/DGT clasifica los incendios forestales mediante tipos DATEX
    equivalentes a forestFire/seriousFire.
    """
    raw = _record_xml_text(record)
    type_value = " ".join(
        str(value)
        for node in record.iter()
        for key, value in node.attrib.items()
        if key.lower().endswith("type")
    ).lower()

    combined = f"{raw} {type_value}"

    return bool(
        re.search(
            r"\bforestfire\b|\bseriousfire\b|forest fire|serious fire",
            combined,
            re.IGNORECASE,
        )
    )


def _datex_is_road_closed(record):
    """
    Acepta únicamente estados explícitos de carretera cerrada.
    No basta con que aparezca la palabra 'corte' en una descripción.
    """
    raw = _record_xml_text(record)
    type_value = " ".join(
        str(value)
        for node in record.iter()
        for key, value in node.attrib.items()
        if key.lower().endswith("type")
    ).lower()

    combined = f"{raw} {type_value}"

    return bool(
        re.search(
            r"\broadclosed\b|road closed|closed road|carriageway closed",
            combined,
            re.IGNORECASE,
        )
    )


def _datex_is_rerouting(record):
    raw = _record_xml_text(record)
    type_value = " ".join(
        str(value)
        for node in record.iter()
        for key, value in node.attrib.items()
        if key.lower().endswith("type")
    ).lower()

    combined = f"{raw} {type_value}"

    return bool(
        re.search(
            r"reroutingmanagement|alternate|itinerary|diversion|desvio|desvío|alternateRoadOrCarriagewayOrLaneLayout",
            combined,
            re.IGNORECASE,
        )
    )


def _datex_record_id(record):
    for key, value in record.attrib.items():
        if key.lower().endswith("id") and value:
            return str(value).strip()

    for node in record.iter():
        for key, value in node.attrib.items():
            if key.lower().endswith("id") and value:
                return str(value).strip()

    return ""


def _datex_road(record):
    return _first_text(
        record,
        (
            "roadName",
            "roadNumber",
            "routeName",
            "routeNumber",
        ),
    )


def _format_km(value):
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.5f}".rstrip("0").rstrip(".")


def _format_km_range(values):
    """
    Convierte todos los PK disponibles de una carretera en:
      PK X
    o:
      PK X–Y

    Nunca inventa un extremo: si INFOCAR solo proporciona un PK, se
    muestra únicamente ese PK.
    """
    values = sorted(
        {
            round(float(value), 5)
            for value in values
            if value is not None
        }
    )

    if not values:
        return ""

    if len(values) == 1:
        return f"PK {_format_km(values[0])}"

    return (
        f"PK {_format_km(values[0])}–"
        f"{_format_km(values[-1])}"
    )


def _datex_km_values(record):
    """
    Extrae TODOS los PK disponibles en el registro DATEX.

    INFOCAR puede publicar los extremos del tramo mediante distintos campos
    o mediante registros diferentes de la misma carretera.
    """
    values = []

    field_names = (
        "kilometerPoint",
        "kilometrePoint",
        "pk",
        "from",
        "to",
        "fromKilometerPoint",
        "toKilometerPoint",
        "fromKilometrePoint",
        "toKilometrePoint",
    )

    for name in field_names:
        for node in _find_descendants(record, (name,)):
            text = _xml_text(node)
            if not text:
                continue

            # Evita interpretar coordenadas/otros números como PK. En los
            # campos de PK buscamos valores numéricos con decimal opcional.
            matches = re.findall(
                r"(?<![\d.-])(\d+(?:[.,]\d+)?)(?![\d.-])",
                text,
            )

            for match in matches:
                try:
                    value = float(match.replace(",", "."))
                except ValueError:
                    continue

                # PK razonable para una carretera española.
                if 0 <= value <= 1000:
                    values.append(value)

    return sorted(set(values))


def _datex_km(record):
    return _format_km_range(
        _datex_km_values(record)
    )


def _datex_direction(record):
    return _first_text(
        record,
        (
            "direction",
            "directionRoad",
            "directionOfTravel",
        ),
    )


def _datex_coordinates(record):
    points = []

    for node in _find_descendants(
        record,
        (
            "pointCoordinates",
        ),
    ):
        lat = _first_text(
            node,
            ("latitude",),
        )
        lon = _first_text(
            node,
            ("longitude",),
        )

        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue

        if -90 <= lat <= 90 and -180 <= lon <= 180:
            points.append((lat, lon))

    return points


def _datex_province_from_road(road):
    if not road:
        return "No disponible"

    match = re.match(
        r"^\s*([A-Z]+)\s*-\s*\d+",
        road.upper(),
    )

    if not match:
        return "No disponible"

    return ANDALUSIA_PROVINCE_CODES.get(
        match.group(1),
        "No disponible",
    )


def _datex_andalusia(record, road):
    """
    Filtrado conservador.

    Para carreteras con prefijo provincial inequívoco usamos el prefijo.
    Para carreteras estatales (A-, AP-, N-, etc.) INFOCAR no siempre expone
    la provincia como campo simple; en ese caso intentamos localizar el
    territorio en el propio registro.
    """
    province = _datex_province_from_road(road)

    if province != "No disponible":
        return province

    raw = _record_xml_text(record)

    for province_name in ANDALUSIA_PROVINCES:
        if province_name.lower() in raw:
            return province_name

    return "No disponible"


def parse_datex_incidents(xml_text, source_url):
    """
    Convierte DATEX II en incidencias de carretera.

    CRITERIO ESTRICTO:
        forestFire/seriousFire
        +
        roadClosed
        +
        no rerouting/diversion

    Una noticia de la Junta no interviene en esta decisión.
    """
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    records = [
        node
        for node in root.iter()
        if _local_name(node.tag) == "situationrecord"
    ]

    incidents = []

    for record in records:

        if not _datex_is_forest_fire(record):
            continue

        if not _datex_is_road_closed(record):
            continue

        if _datex_is_rerouting(record):
            continue

        road = _datex_road(record)

        if not road:
            continue

        province = _datex_andalusia(
            record,
            road,
        )

        # No queremos generar alertas de provincias fuera de Andalucía.
        if (
            province == "No disponible"
            and not any(
                province_name.lower() in _record_xml_text(record)
                for province_name in ANDALUSIA_PROVINCES
            )
        ):
            continue

        if province == "No disponible":
            continue

        km = _datex_km(record)
        direction = _datex_direction(record)
        coordinates = _datex_coordinates(record)
        record_id = _datex_record_id(record)

        detected_at = datetime.now(
            timezone.utc
        ).isoformat()

        incidents.append(
            {
                "fire": "Incendio forestal",
                "province": province,
                "municipality": "No disponible",
                "road": road,
                "section": km,
                "km_values": _datex_km_values(record),
                "direction": direction,
                "closure_type": "Total",
                "detected_at": detected_at,
                "fire_status": (
                    "Incendio forestal confirmado "
                    "por INFOCAR/DGT"
                ),
                "infoca": (
                    "Pendiente de cotejo INFOCA"
                ),
                "dgt": "Corte confirmado por INFOCAR/DGT",
                "other_sources": source_url,
                "source_url": source_url,
                "source_title": DGT_SOURCE_NAME,
                "datex_id": record_id,
                "coordinates": coordinates,
            }
        )

    return incidents



def merge_datex_road_records(items):
    """
    Consolida registros DATEX de la misma carretera y del mismo incendio.

    Es especialmente importante para INFOCAR cuando publica dos registros
    para los dos extremos de un tramo: ambos deben acabar en un único aviso.
    """
    groups = {}

    for item in items:
        road = normalize(item.get("road", "")).upper()
        province = normalize(item.get("province", "")).lower()

        if not road:
            continue

        # No usamos datex_id como clave aquí: dos IDs distintos pueden ser
        # precisamente los dos extremos del mismo tramo.
        key = f"{province}|{road}"

        if key not in groups:
            groups[key] = dict(item)
            groups[key]["km_values"] = list(
                item.get("km_values") or []
            )
            continue

        current = groups[key]

        # Unir PK de todos los registros.
        values = list(current.get("km_values") or [])
        values.extend(item.get("km_values") or [])

        # También recuperamos cualquier PK que haya quedado en section.
        for match in re.findall(
            r"(?<![\d.-])(\d+(?:[.,]\d+)?)(?![\d.-])",
            normalize(item.get("section", "")),
        ):
            try:
                values.append(
                    float(match.replace(",", "."))
                )
            except ValueError:
                pass

        values = sorted(set(round(v, 5) for v in values))
        current["km_values"] = values
        current["section"] = _format_km_range(values)

        # Conservamos coordenadas de todos los registros.
        coords = list(current.get("coordinates") or [])
        for coord in item.get("coordinates") or []:
            if coord not in coords:
                coords.append(coord)
        current["coordinates"] = coords

        # Combinar fuentes oficiales.
        existing_sources = {
            current.get("source_url", ""),
        }
        if item.get("source_url"):
            existing_sources.add(item["source_url"])

        current["source_urls"] = [
            url for url in existing_sources if url
        ]

        # Mantener la información no vacía más completa.
        for field, value in item.items():
            if field in {
                "km_values",
                "section",
                "coordinates",
                "source_urls",
            }:
                continue

            if value in ("", None, "No disponible"):
                continue

            if current.get(field) in (
                "",
                None,
                "No disponible",
            ):
                current[field] = value

    return list(groups.values())


def fetch_datex_incidents():
    """
    Consulta las publicaciones DATEX II de DGT/INFOCAR.

    Se intenta cada endpoint de forma independiente. Un fallo en uno no
    impide utilizar el otro.
    """
    all_incidents = []

    for url in DGT_DATEX_URLS:

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            response.raise_for_status()

            parsed = parse_datex_incidents(
                response.text,
                url,
            )

            all_incidents.extend(
                parsed
            )

        except Exception:
            continue

    merged = merge_datex_road_records(
        all_incidents
    )

    return deduplicate_datex_incidents(
        merged
    )


def deduplicate_datex_incidents(items):
    """
    Deduplica el mismo registro que aparece simultáneamente en INFOCAR y NAP.

    Prioridad:
        identificador DATEX
        carretera + PK + sentido
    """
    unique = {}

    for item in items:

        datex_id = item.get(
            "datex_id"
        )

        if datex_id:
            key = f"id|{normalize(datex_id).lower()}"
        else:
            key = "|".join(
                normalize(
                    item.get(field, "")
                ).lower()
                for field in (
                    "province",
                    "road",
                    "direction",
                )
            )

        if key not in unique:
            unique[key] = item
            continue

        current = unique[key]

        for field, value in item.items():

            if value in (
                "",
                None,
                "No disponible",
            ):
                continue

            if current.get(field) in (
                "",
                None,
                "No disponible",
            ):
                current[field] = value

    return list(
        unique.values()
    )


# ============================================================
# ARTÍCULOS OFICIALES
# ============================================================

def get_candidate_articles():

    response = get(
        JUNTA_SEARCH_URL
    )

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

    return list(
        unique.values()
    )


# ============================================================
# ANALIZAR ARTÍCULO
# ============================================================

def parse_article(article):

    response = get(
        article["url"]
    )

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

    # Debe existir un incendio.
    if not contains_any(
        full_text,
        FIRE_KEYWORDS,
    ):
        return None

    province = find_province(
        full_text
    )

    if province == "No disponible":
        return None

    # --------------------------------------------------------
    # CARRETERAS RELACIONADAS DIRECTAMENTE CON EL CORTE
    # --------------------------------------------------------

    closure_roads = extract_roads_near_closure(
        full_text
    )

    # Filtrar carreteras provinciales inequívocas que pertenezcan a otra
    # provincia. Evita contaminar una incidencia cuando una noticia menciona
    # varias provincias.
    road_province = {
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

    filtered_roads = []

    for road in closure_roads:
        match = re.match(
            r"^([A-Z]+)-\d{1,5}$",
            road,
            re.IGNORECASE,
        )

        if not match:
            filtered_roads.append(road)
            continue

        prefix = match.group(1).upper()
        expected_province = road_province.get(prefix)

        if (
            expected_province is None
            or province == "No disponible"
            or expected_province == province
        ):
            filtered_roads.append(road)

    closure_roads = filtered_roads

    has_closure = contains_any(
        full_text,
        CLOSURE_KEYWORDS,
    )

    has_reopening = contains_any(
        full_text,
        REOPEN_KEYWORDS,
    )

    # Una palabra de corte sin carretera relacionada
    # NO es suficiente.
    if has_closure and not closure_roads:
        return None

    if not has_closure and not has_reopening:
        return None

    municipality = extract_municipality(
        title,
        full_text,
    )

    fire_name = extract_fire_name(
        title,
        municipality,
    )

    section = extract_section(
        full_text
    )

    direction = extract_direction(
        full_text
    )

    detected_at = datetime.now(
        timezone.utc
    ).isoformat()

    roads_text = ", ".join(
        closure_roads
    )

    # ========================================================
    # CORTE ACTIVO
    # ========================================================

    if has_closure and closure_roads:

        return {
            "fire": fire_name,
            "province": province,
            "municipality": municipality,
            "road": roads_text,
            "section": section,
            "direction": direction,
            "closure_type": "Total / no especificado",
            "detected_at": detected_at,
            "fire_status": (
                "Incendio forestal confirmado "
                "por fuente oficial"
            ),
            "infoca": (
                "Información oficial "
                "Junta/EMA/INFOCA"
            ),
            "dgt": "Pendiente de cotejo DGT",
            "other_sources": article["url"],
            "source_url": article["url"],
            "source_title": title,
        }

    # ========================================================
    # REAPERTURA
    # ========================================================

    if has_reopening and closure_roads:

        return {
            "fire": fire_name,
            "province": province,
            "municipality": municipality,
            "road": roads_text,
            "section": section,
            "direction": direction,
            "reopened_at": detected_at,
            "source": article["url"],
            "source_title": title,
        }

    return None


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def incident_source_key(item):
    """
    Agrupa publicaciones diferentes que describen
    el mismo corte.

    NO utiliza el titular de la noticia.
    """

    values = [
        item.get(
            "province",
            "",
        ),

        item.get(
            "municipality",
            "",
        ),

        item.get(
            "road",
            "",
        ),

        item.get(
            "section",
            "",
        ),

        item.get(
            "direction",
            "",
        ),
    ]

    return "|".join(
        normalize(value).lower()
        for value in values
    )


def deduplicate_incidents(items):
    """
    Conserva una sola incidencia por combinación de:

        provincia
        municipio
        carretera
        tramo
        sentido
    """

    unique = {}

    for item in items:

        key = incident_source_key(
            item
        )

        if key not in unique:

            unique[key] = item

            continue

        current = unique[key]

        # Conserva información adicional si
        # alguna de las noticias la aporta.
        for field, value in item.items():

            if value in (
                "",
                None,
                "No disponible",
            ):
                continue

            if current.get(field) in (
                None,
                "",
                "No disponible",
            ):

                current[field] = value

    return list(
        unique.values()
    )


# ============================================================
# API UTILIZADA POR main.py
# ============================================================

def fetch_official_incidents():
    """
    Fuente principal para los CORTES:
        INFOCAR/DGT DATEX II.

    Las noticias de Junta/INFOCA ya NO pueden crear por sí mismas una
    incidencia de carretera. Solo se utilizarán posteriormente para
    enriquecer el incendio.
    """

    return fetch_datex_incidents()


def fetch_official_reopenings():
    """
    Las reaperturas se detectarán a partir de la desaparición/cambio del
    registro DATEX en combinación con la confirmación positiva disponible.

    En esta versión no se considera una carretera reabierta simplemente
    porque desaparezca de una noticia de Junta.
    """
    return []
