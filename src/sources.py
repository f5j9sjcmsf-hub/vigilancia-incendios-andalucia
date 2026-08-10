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

DGT_URLS = (
    "https://infocar.dgt.es/datex2/v3/dgt/"
    "SituationPublication/incidencias.xml",

    "https://nap.dgt.es/datex2/v3/dgt/"
    "SituationPublication/datex2_v36.xml",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; VigilanciaIncendiosAndalucia/4.0)"
    )
}

TIMEOUT = 30


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
# PREFIJOS PROVINCIALES
# ============================================================

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

    return any(
        keyword.lower() in text
        for keyword in keywords
    )


def local_now():
    return datetime.now(
        timezone.utc
    ).astimezone()


def display_datetime():
    return local_now().strftime(
        "%d/%m/%Y %H:%M"
    )


def normalize_road(value):
    value = normalize(value).upper()

    value = re.sub(
        r"\s+",
        "",
        value,
    )

    value = re.sub(
        r"^([A-Z]{1,5})[- ]?(\d{1,5})$",
        r"\1-\2",
        value,
    )

    return value


# ============================================================
# DATEX II - UTILIDADES XML
# ============================================================

def _local_name(tag):
    if not tag:
        return ""

    return tag.rsplit(
        "}",
        1,
    )[-1].lower()


def _tag_text(element, names):
    if element is None:
        return ""

    wanted = {
        name.lower()
        for name in names
    }

    for child in element.iter():

        if _local_name(child.tag) not in wanted:
            continue

        value = normalize(
            "".join(
                child.itertext()
            )
        )

        if value:
            return value

    return ""


def _record_text(record):
    return normalize(
        " ".join(
            node.text or ""
            for node in record.iter()
            if node.text
        )
    ).lower()


# ============================================================
# DATEX - IDENTIFICACIÓN DEL TIPO DE INCIDENCIA
# ============================================================

def _record_is_fire(record):
    raw = _record_text(record)

    type_values = " ".join(
        str(value)
        for node in record.iter()
        for key, value in node.attrib.items()
        if _local_name(key) == "type"
    ).lower()

    combined = (
        f"{raw} {type_values}"
    )

    return bool(
        re.search(
            r"\bforestfire\b"
            r"|\bseriousfire\b"
            r"|forest fire"
            r"|serious fire",
            combined,
            re.IGNORECASE,
        )
    )


def _record_is_road_closed(record):
    raw = _record_text(record)

    type_values = " ".join(
        str(value)
        for node in record.iter()
        for key, value in node.attrib.items()
        if _local_name(key) == "type"
    ).lower()

    combined = (
        f"{raw} {type_values}"
    )

    return bool(
        re.search(
            r"\broadclosed\b"
            r"|road closed"
            r"|closed road"
            r"|carriageway closed",
            combined,
            re.IGNORECASE,
        )
    )


def _record_is_rerouting(record):
    raw = _record_text(record)

    type_values = " ".join(
        str(value)
        for node in record.iter()
        for key, value in node.attrib.items()
        if _local_name(key) == "type"
    ).lower()

    combined = (
        f"{raw} {type_values}"
    )

    return bool(
        re.search(
            r"reroutingmanagement"
            r"|alternate"
            r"|itinerary"
            r"|diversion"
            r"|desvio"
            r"|desvío"
            r"|alternateroadorcarriagewayorlaneslayout",
            combined,
            re.IGNORECASE,
        )
    )


# ============================================================
# DATEX - CARRETERA
# ============================================================

def _datex_road(record):
    value = _tag_text(
        record,
        (
            "roadName",
            "roadNumber",
            "roadIdentifier",
            "routeName",
            "routeNumber",
        ),
    )

    return normalize_road(value)


# ============================================================
# DATEX - PK
# ============================================================

def _clean_km(value):
    """
    Devuelve un PK solamente cuando el contenido representa
    inequívocamente un valor kilométrico.

    Nunca interpreta coordenadas ni textos de localización.
    """

    value = normalize(value)

    if not value:
        return ""

    if re.search(
        r"\b(?:pk|p\.k\.|km|kil[oó]metro|kil[oó]metros?)\b",
        value,
        re.IGNORECASE,
    ):
        match = re.search(
            r"(?<!\d)"
            r"(\d+(?:[.,]\d+)?)"
            r"(?!\d)",
            value,
        )

        if not match:
            return ""

        return match.group(1).replace(
            ",",
            ".",
        )

    # Un número puro puede ser un PK válido.
    if re.fullmatch(
        r"\d+(?:[.,]\d+)?",
        value,
    ):
        return value.replace(
            ",",
            ".",
        )

    return ""


def _datex_km_values(record):
    """
    Extrae TODOS los PK inequívocamente publicados por DATEX.

    Se contemplan las distintas estructuras que hemos encontrado
    en INFOCAR/NAP.

    IMPORTANTE:
    Los campos from/to SOLO se aceptan cuando contienen exclusivamente
    un PK o un número puro. Así evitamos interpretar coordenadas,
    municipios u otros valores como PK.
    """

    values = []

    explicit_fields = (
        "kilometerPoint",
        "kilometrePoint",
        "kilometricPoint",
        "kilometerPointStart",
        "kilometerPointEnd",
        "kilometrePointStart",
        "kilometrePointEnd",
        "fromKilometerPoint",
        "toKilometerPoint",
        "fromKilometrePoint",
        "toKilometrePoint",
        "fromKilometricPoint",
        "toKilometricPoint",
        "startKilometerPoint",
        "endKilometerPoint",
        "startKilometrePoint",
        "endKilometrePoint",
        "startKm",
        "endKm",
        "fromPk",
        "toPk",
        "pk",
    )

    for name in explicit_fields:

        for node in record.iter():

            if _local_name(node.tag) != name.lower():
                continue

            text = normalize(
                "".join(
                    node.itertext()
                )
            )

            if not text:
                continue

            value = _clean_km(text)

            if not value:
                continue

            try:
                number = float(
                    value.replace(",", ".")
                )
            except ValueError:
                continue

            if 0 <= number <= 1000:
                values.append(
                    number
                )

    # DATEX puede utilizar from/to.
    # Solo se admiten si son números puros o "PK X".
    for name in (
        "from",
        "to",
    ):

        for node in record.iter():

            if _local_name(node.tag) != name:
                continue

            text = normalize(
                "".join(
                    node.itertext()
                )
            )

            if not re.fullmatch(
                r"(?:PK\s*)?"
                r"\d+(?:[.,]\d+)?",
                text,
                re.IGNORECASE,
            ):
                continue

            value = _clean_km(text)

            if not value:
                continue

            try:
                number = float(
                    value.replace(",", ".")
                )
            except ValueError:
                continue

            if 0 <= number <= 1000:
                values.append(
                    number
                )

    return sorted(
        set(
            round(
                value,
                6,
            )
            for value in values
        )
    )


def _format_km_value(value):
    text = (
        f"{float(value):.6f}"
        .rstrip("0")
        .rstrip(".")
    )

    return text


def _format_km_values(values):
    values = sorted(
        set(
            round(
                float(value),
                6,
            )
            for value in values
            if value is not None
        )
    )

    if not values:
        return ""

    if len(values) == 1:
        return (
            f"PK {_format_km_value(values[0])}"
        )

    return (
        f"PK {_format_km_value(values[0])}"
        f"–"
        f"{_format_km_value(values[-1])}"
    )


def _datex_km(record):
    return _format_km_values(
        _datex_km_values(record)
    )


# ============================================================
# DATEX - SENTIDO
# ============================================================

def _datex_direction(record):
    return _tag_text(
        record,
        (
            "direction",
            "directionalFlow",
            "directionRoad",
            "directionOfTravel",
            "carriageway",
            "affectedCarriageway",
        ),
    )


# ============================================================
# DATEX - LOCALIZACIÓN
# ============================================================

def _datex_location_text(record):
    values = []

    for name in (
        "municipality",
        "municipalityName",
        "localityName",
        "townName",
        "administrativeAreaName",
        "roadName",
        "descriptor",
    ):

        value = _tag_text(
            record,
            (name,),
        )

        if value and value not in values:
            values.append(value)

    return normalize(
        " ".join(values)
    )


# ============================================================
# DATEX - COORDENADAS
# ============================================================

def _datex_coordinates(record):
    lat = None
    lon = None

    for node in record.iter():

        local = _local_name(
            node.tag
        )

        if local == "latitude" and lat is None:
            try:
                lat = float(
                    normalize(node.text)
                )
            except (
                TypeError,
                ValueError,
            ):
                pass

        if local == "longitude" and lon is None:
            try:
                lon = float(
                    normalize(node.text)
                )
            except (
                TypeError,
                ValueError,
            ):
                pass

    if lat is None or lon is None:
        return None, None

    if not (
        -90 <= lat <= 90
        and
        -180 <= lon <= 180
    ):
        return None, None

    return lat, lon


# ============================================================
# DATEX - IDENTIFICADORES
# ============================================================

def _datex_record_id(record):
    for key in (
        "id",
        "recordId",
        "situationRecordId",
    ):

        value = _tag_text(
            record,
            (key,),
        )

        if value:
            return value

    for key, value in record.attrib.items():

        if _local_name(key) in (
            "id",
            "recordid",
        ):

            value = normalize(
                value
            )

            if value:
                return value

    return ""


def _datex_situation_id(situation):
    for key, value in situation.attrib.items():

        local = _local_name(key)

        if local in (
            "id",
            "situationid",
            "situationnumber",
        ):

            value = normalize(
                value
            )

            if value:
                return value

    for child in list(situation):

        local = _local_name(
            child.tag
        )

        if local in (
            "id",
            "situationid",
            "situationnumber",
        ):

            value = normalize(
                child.text
            )

            if value:
                return value

    return ""


# ============================================================
# PARSER DATEX
# ============================================================

def parse_datex_xml(
    xml_text,
    source_url,
):
    """
    Extrae exclusivamente:

        forestFire / seriousFire
        +
        roadClosed

    Las desviaciones no generan cortes.

    Conserva situation_id porque una misma emergencia DATEX
    puede contener varias carreteras y municipios.
    """

    if not xml_text:
        return []

    try:
        root = ET.fromstring(
            xml_text
        )
    except ET.ParseError:
        return []

    situations = [
        node
        for node in root.iter()
        if _local_name(node.tag)
        == "situation"
    ]

    if not situations:
        situations = [root]

    results = []
    seen = set()

    for index, situation in enumerate(
        situations
    ):

        situation_id = (
            _datex_situation_id(
                situation
            )
        )

        if not situation_id:
            situation_id = (
                f"container-{index}"
            )

        records = [
            node
            for node in situation.iter()
            if _local_name(node.tag)
            == "situationrecord"
        ]

        for record in records:

            if not _record_is_fire(
                record
            ):
                continue

            if not _record_is_road_closed(
                record
            ):
                continue

            if _record_is_rerouting(
                record
            ):
                continue

            road = _datex_road(
                record
            )

            if not road:
                continue

            km_values = (
                _datex_km_values(
                    record
                )
            )

            section = (
                _format_km_values(
                    km_values
                )
            )

            direction = (
                _datex_direction(
                    record
                )
            )

            location_text = (
                _datex_location_text(
                    record
                )
            )

            lat, lon = (
                _datex_coordinates(
                    record
                )
            )

            record_id = (
                _datex_record_id(
                    record
                )
            )

            unique_key = (
                record_id
                or (
                    situation_id,
                    road,
                    section,
                    direction,
                    lat,
                    lon,
                )
            )

            if unique_key in seen:
                continue

            seen.add(
                unique_key
            )

            results.append(
                {
                    "road": road,
                    "section": section,
                    "km_values": km_values,
                    "direction": direction,
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


# ============================================================
# OBTENER CORTES INFOCAR
# ============================================================

def fetch_datex_closures():
    """
    Consulta INFOCAR y NAP.

    Deduplica registros idénticos entre ambas publicaciones,
    pero NO elimina registros con situation_id diferentes.
    """

    all_records = []

    for url in DGT_URLS:

        try:
            response = get(url)

            records = parse_datex_xml(
                response.text,
                url,
            )

        except Exception:
            continue

        all_records.extend(
            records
        )

    unique = {}

    for item in all_records:

        datex_id = normalize(
            item.get(
                "datex_id",
                "",
            )
        )

        if datex_id:

            key = (
                "id|"
                + datex_id.lower()
            )

        else:

            key = "|".join(
                (
                    normalize(
                        item.get(
                            "road",
                            "",
                        )
                    ).lower(),

                    normalize(
                        item.get(
                            "section",
                            "",
                        )
                    ).lower(),

                    normalize(
                        item.get(
                            "direction",
                            "",
                        )
                    ).lower(),

                    normalize(
                        item.get(
                            "situation_id",
                            "",
                        )
                    ).lower(),
                )
            )

        if key not in unique:

            unique[key] = item

            continue

        current = unique[key]

        # Si las dos fuentes contienen el mismo registro,
        # conservar cualquier información adicional.
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
# INFOCA / JUNTA
# ============================================================

def find_province(text):
    text = normalize(text)
    lower = text.lower()

    aliases = {
        "almeria": "Almería",
        "almería": "Almería",
        "cadiz": "Cádiz",
        "cádiz": "Cádiz",
        "cordoba": "Córdoba",
        "córdoba": "Córdoba",
        "granada": "Granada",
        "huelva": "Huelva",
        "jaen": "Jaén",
        "jaén": "Jaén",
        "malaga": "Málaga",
        "málaga": "Málaga",
        "sevilla": "Sevilla",
    }

    patterns = (
        r"provincia\s+(?:de|del)\s+"
        r"(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|"
        r"huelva|ja[eé]n|m[aá]laga|sevilla)",

        r"\("
        r"(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|"
        r"huelva|ja[eé]n|m[aá]laga|sevilla)"
        r"\)",

        r"\ben\s+"
        r"(almer[ií]a|c[aá]diz|c[oó]rdoba|granada|"
        r"huelva|ja[eé]n|m[aá]laga|sevilla)"
        r"\b",
    )

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

    found = []

    for alias, province in aliases.items():

        if re.search(
            rf"\b{re.escape(alias)}\b",
            lower,
        ):

            if province not in found:
                found.append(
                    province
                )

    if len(found) == 1:
        return found[0]

    return "No disponible"


# ============================================================
# CARRETERAS EN TEXTO INFOCA
# ============================================================

def extract_roads(text):
    pattern = re.compile(
        r"\b("
        r"A|AP|N|"
        r"AL|CA|CO|GR|H|HU|J|JA|MA|SE|"
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

        road = normalize_road(
            road
        )

        if road not in roads:
            roads.append(
                road
            )

    return roads


# ============================================================
# MUNICIPIO INFOCA
# ============================================================

def clean_municipality(value):
    value = normalize(
        value
    )

    value = re.split(
        r"\s+(?:motiva|provoca|obliga|"
        r"afecta|afectando|ha|y|pese\s+a|"
        r"mientras|tras|ante)\s+",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    return value.strip(
        " .,:;–—-"
    )


def extract_municipality(
    title,
    text,
):
    """
    Intenta obtener el municipio del incendio.

    Se da prioridad al titular y a expresiones del tipo:

        incendio de Niebla
        incendio en Niebla
        incendio forestal de Niebla

    También acepta la forma:

        incendio de Niebla (Huelva)
    """

    sources = (
        title,
        text[:8000],
    )

    patterns = (
        r"incendio\s+"
        r"(?:forestal\s+)?"
        r"(?:de|en)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:()–—-]{1,60})",

        r"incendio\s+"
        r"(?:forestal\s+)?"
        r"(?:de|en)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:–—-]{1,60})"
        r"\s*\(",

        r"fuego\s+"
        r"(?:forestal\s+)?"
        r"(?:de|en)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:()–—-]{1,60})",
    )

    for source in sources:

        for pattern in patterns:

            match = re.search(
                pattern,
                source,
                re.IGNORECASE,
            )

            if not match:
                continue

            value = clean_municipality(
                match.group(1)
            )

            if (
                value
                and
                value.lower()
                not in (
                    "andalucía",
                    "andalucia",
                    "la provincia",
                    "la zona",
                )
                and len(value) <= 60
            ):
                return value

    return "No disponible"


# ============================================================
# NOMBRE DEL INCENDIO
# ============================================================

def extract_fire_name(
    title,
    text,
    municipality,
):
    """
    INFOCA es la fuente del nombre.

    Prioridad:

    1. Hashtag INFOCA del tipo #IIFFNiebla
    2. Expresión "Incendio de Niebla"
    3. Municipio identificado

    No utiliza el titular periodístico completo como nombre.
    """

    full_text = (
        f"{title} {text}"
    )

    # --------------------------------------------------------
    # HASHTAG INFOCA
    # --------------------------------------------------------

    hashtag_pattern = re.compile(
        r"#iiff"
        r"([a-záéíóúüñ][a-záéíóúüñ0-9_-]*)",
        re.IGNORECASE,
    )

    hashtags = hashtag_pattern.findall(
        full_text
    )

    for value in hashtags:

        value = normalize(
            value
        ).strip(
            "_- "
        )

        if not value:
            continue

        # Normalización básica del identificador
        # #IIFFNiebla -> Niebla
        name = value[0].upper() + value[1:]

        return (
            f"Incendio de {name}"
        )

    # --------------------------------------------------------
    # EXPRESIÓN EXPLÍCITA EN TEXTO
    # --------------------------------------------------------

    patterns = (
        r"incendio\s+"
        r"(?:forestal\s+)?"
        r"(?:de|en)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:()–—-]{1,60})",

        r"fuego\s+"
        r"(?:forestal\s+)?"
        r"(?:de|en)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][^,.;:()–—-]{1,60})",
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            title,
            re.IGNORECASE,
        )

        if not match:
            continue

        value = clean_municipality(
            match.group(1)
        )

        if value:
            return (
                f"Incendio de {value}"
            )

    # --------------------------------------------------------
    # MUNICIPIO
    # --------------------------------------------------------

    if municipality != "No disponible":

        return (
            f"Incendio de {municipality}"
        )

    return "Incendio forestal"


# ============================================================
# ARTÍCULOS INFOCA
# ============================================================

def get_candidate_articles():
    try:
        response = get(
            JUNTA_SEARCH_URL
        )

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

        if (
            "juntadeandalucia.es"
            not in href
        ):
            continue

        candidates.append(
            {
                "title": title,
                "url": href,
            }
        )

    unique = {}

    for item in candidates:
        unique[
            item["url"]
        ] = item

    return list(
        unique.values()
    )


def parse_infoca_article(article):
    try:
        response = get(
            article["url"]
        )

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

    full_text = (
        f"{title} {body}"
    )

    if not contains_any(
        full_text,
        FIRE_KEYWORDS,
    ):
        return None

    province = find_province(
        full_text
    )

    municipality = (
        extract_municipality(
            title,
            full_text,
        )
    )

    fire_name = (
        extract_fire_name(
            title,
            full_text,
            municipality,
        )
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


# ============================================================
# AGRUPAR ACTUALIZACIONES INFOCA
# ============================================================

def _fire_group_key(item):
    """
    Agrupa por nombre real del incendio.

    Esto evita que dos noticias del mismo incendio,
    con titulares diferentes, creen dos incendios.
    """

    fire = normalize(
        item.get(
            "fire",
            "",
        )
    ).lower()

    if fire and fire != "incendio forestal":
        return f"fire|{fire}"

    municipality = normalize(
        item.get(
            "municipality",
            "",
        )
    ).lower()

    province = normalize(
        item.get(
            "province",
            "",
        )
    ).lower()

    return (
        f"location|"
        f"{province}|"
        f"{municipality}"
    )


def _merge_infoca_fire_updates(
    items
):
    if not items:
        return None

    base = sorted(
        items,
        key=lambda item: (
            item.get(
                "fire",
                ""
            ) == "Incendio forestal",

            item.get(
                "municipality",
                ""
            ) == "No disponible",
        ),
    )[0]

    fire_name = base.get(
        "fire",
        "Incendio forestal",
    )

    province = base.get(
        "province",
        "No disponible",
    )

    municipality = base.get(
        "municipality",
        "No disponible",
    )

    roads = []
    sources = []

    for item in items:

        item_fire = item.get(
            "fire",
            "",
        )

        if (
            fire_name
            == "Incendio forestal"
            and item_fire
        ):
            fire_name = item_fire

        item_province = item.get(
            "province",
            "No disponible",
        )

        if (
            province == "No disponible"
            and item_province
            != "No disponible"
        ):
            province = item_province

        item_municipality = item.get(
            "municipality",
            "No disponible",
        )

        if (
            municipality
            == "No disponible"
            and item_municipality
            != "No disponible"
        ):
            municipality = (
                item_municipality
            )

        for road in item.get(
            "roads",
            [],
        ):

            road = normalize_road(
                road
            )

            if (
                road
                and road not in roads
            ):
                roads.append(
                    road
                )

        source = item.get(
            "source_url",
            "",
        )

        if (
            source
            and source not in sources
        ):
            sources.append(
                source
            )

    return {
        **base,
        "fire": fire_name,
        "province": province,
        "municipality": municipality,
        "roads": roads,
        "source_urls": sources,
        "source_url": (
            sources[0]
            if sources
            else base.get(
                "source_url",
                "",
            )
        ),
    }


def fetch_infoca_fires():
    parsed = []

    for article in get_candidate_articles():

        item = parse_infoca_article(
            article
        )

        if item:
            parsed.append(
                item
            )

    groups = {}

    for item in parsed:

        key = _fire_group_key(
            item
        )

        groups.setdefault(
            key,
            [],
        ).append(item)

    fires = []

    for items in groups.values():

        merged = (
            _merge_infoca_fire_updates(
                items
            )
        )

        if merged:
            fires.append(
                merged
            )

    return fires


# ============================================================
# VINCULACIÓN INFOCAR ↔ INFOCA
# ============================================================

def _road_belongs_to_province(
    road,
    province,
):
    """
    SOLO sirve como información auxiliar.

    IMPORTANTE:
    NO se utiliza para excluir una carretera.

    Un incendio puede propagarse a otra provincia.
    """

    match = re.match(
        r"^([A-Z]{1,5})-\d{1,5}$",
        normalize_road(road),
    )

    if not match:
        return True

    road_province = ROAD_PROVINCES.get(
        match.group(1)
    )

    if road_province is None:
        return True

    if province == "No disponible":
        return True

    return (
        road_province
        == province
    )


def _haversine_km(
    lat1,
    lon1,
    lat2,
    lon2,
):
    if None in (
        lat1,
        lon1,
        lat2,
        lon2,
    ):
        return None

    from math import (
        radians,
        sin,
        cos,
        asin,
        sqrt,
    )

    radius = 6371.0088

    dlat = radians(
        lat2 - lat1
    )

    dlon = radians(
        lon2 - lon1
    )

    a = (
        sin(dlat / 2) ** 2
        +
        cos(radians(lat1))
        *
        cos(radians(lat2))
        *
        sin(dlon / 2) ** 2
    )

    return (
        2
        * radius
        * asin(
            sqrt(a)
        )
    )


def _direct_dgt_matches_fire(
    dgt_item,
    fire,
):
    """
    Asociación directa.

    Una carretera puede coincidir aunque pertenezca
    a otra provincia.

    Esto es deliberado para permitir incendios
    que crucen límites provinciales.
    """

    road = normalize_road(
        dgt_item.get(
            "road",
            "",
        )
    )

    fire_roads = {
        normalize_road(
            value
        )
        for value in fire.get(
            "roads",
            [],
        )
        if normalize_road(
            value
        )
    }

    # Coincidencia por carretera.
    if (
        road
        and road in fire_roads
    ):
        return True

    # Coincidencia por municipio.
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

    if (
        municipality
        and municipality != "no disponible"
        and municipality in location
    ):
        return True

    return False


def _dgt_matches_fire(
    dgt_item,
    fire,
    dgt_items=None,
):
    """
    Vinculación directa o por situation_id.

    Si un registro de una misma situation DATEX
    ya está vinculado al incendio, todos los demás
    cortes forestFire + roadClosed de esa misma
    situation pertenecen al mismo conjunto.
    """

    if _direct_dgt_matches_fire(
        dgt_item,
        fire,
    ):
        return True

    situation_id = normalize(
        dgt_item.get(
            "situation_id",
            "",
        )
    )

    if (
        situation_id
        and dgt_items
    ):

        for other in dgt_items:

            if other is dgt_item:
                continue

            other_situation = normalize(
                other.get(
                    "situation_id",
                    "",
                )
            )

            if (
                other_situation
                != situation_id
            ):
                continue

            if _direct_dgt_matches_fire(
                other,
                fire,
            ):
                return True

    return False


# ============================================================
# EXPANSIÓN GEOGRÁFICA DEL INCENDIO
# ============================================================

def _expand_fire_dgt_cluster(
    fire,
    direct_matches,
    dgt_items,
):
    """
    Amplía el conjunto de carreteras del incendio.

    PRIORIDAD:

    1. Registros directamente vinculados.
    2. Otros registros de la misma situation_id.
    3. Proximidad geográfica a un registro ya vinculado.

    IMPORTANTE:
    NO se aplica ningún filtro provincial.

    Esto permite:

        Huelva -> Sevilla

    cuando el incendio realmente se ha extendido.
    """

    if not direct_matches:
        return []

    selected = list(
        direct_matches
    )

    selected_keys = {
        (
            item.get(
                "datex_id"
            )
            or id(item)
        )
        for item in selected
    }

    # --------------------------------------------------------
    # PRIMERO: TODA LA SITUATION
    # --------------------------------------------------------

    changed = True

    while changed:

        changed = False

        selected_situations = {
            normalize(
                item.get(
                    "situation_id",
                    "",
                )
            )
            for item in selected
            if normalize(
                item.get(
                    "situation_id",
                    "",
                )
            )
        }

        for candidate in dgt_items:

            candidate_key = (
                candidate.get(
                    "datex_id"
                )
                or id(candidate)
            )

            if candidate_key in selected_keys:
                continue

            candidate_situation = normalize(
                candidate.get(
                    "situation_id",
                    "",
                )
            )

            if (
                candidate_situation
                and candidate_situation
                in selected_situations
            ):

                selected.append(
                    candidate
                )

                selected_keys.add(
                    candidate_key
                )

                changed = True

    # --------------------------------------------------------
    # SEGUNDO: PROXIMIDAD
    # --------------------------------------------------------

    radius_km = 35.0

    changed = True

    while changed:

        changed = False

        for candidate in dgt_items:

            candidate_key = (
                candidate.get(
                    "datex_id"
                )
                or id(candidate)
            )

            if candidate_key in selected_keys:
                continue

            for anchor in selected:

                distance = _haversine_km(
                    candidate.get(
                        "lat"
                    ),
                    candidate.get(
                        "lon"
                    ),
                    anchor.get(
                        "lat"
                    ),
                    anchor.get(
                        "lon"
                    ),
                )

                if (
                    distance is not None
                    and distance <= radius_km
                ):

                    selected.append(
                        candidate
                    )

                    selected_keys.add(
                        candidate_key
                    )

                    changed = True

                    break

    return selected


# ============================================================
# AGRUPAR CARRETERAS
# ============================================================

def _parse_section_values(
    section
):
    if not section:
        return []

    values = re.findall(
        r"(?<!\d)"
        r"(\d+(?:[.,]\d+)?)"
        r"(?!\d)",
        str(section),
    )

    result = []

    for value in values:

        try:
            result.append(
                float(
                    value.replace(
                        ",",
                        ".",
                    )
                )
            )

        except ValueError:
            continue

    return result


def _merge_dgt_road_details(
    dgt_items
):
    """
    Agrupa por carretera.

    Todos los PK disponibles de esa carretera
    se conservan.

    Ejemplo:

        HU-3106 PK 2.5
        HU-3106 PK 20.8

    pasa a:

        HU-3106 PK 2.5–20.8

    Si solamente existe un PK:

        HU-3106 PK 20.8

    Si no existe información kilométrica:

        HU-3106

    No se fabrica ningún PK.
    """

    grouped = {}

    for item in dgt_items:

        road = normalize_road(
            item.get(
                "road",
                "",
            )
        )

        if not road:
            continue

        key = road

        if key not in grouped:

            grouped[key] = {
                "road": road,
                "direction": normalize(
                    item.get(
                        "direction",
                        "",
                    )
                ),
                "pk_values": [],
            }

        entry = grouped[key]

        # ----------------------------------------------------
        # PK ESTRUCTURADO
        # ----------------------------------------------------

        for value in (
            item.get(
                "km_values",
                []
            )
            or []
        ):

            try:
                entry[
                    "pk_values"
                ].append(
                    float(value)
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        # ----------------------------------------------------
        # PK NORMALIZADO EN SECTION
        # ----------------------------------------------------

        values = (
            _parse_section_values(
                item.get(
                    "section",
                    "",
                )
            )
        )

        entry[
            "pk_values"
        ].extend(
            values
        )

        if not entry["direction"]:

            entry[
                "direction"
            ] = normalize(
                item.get(
                    "direction",
                    "",
                )
            )

    details = []

    for entry in grouped.values():

        values = sorted(
            set(
                round(
                    value,
                    6,
                )
                for value
                in entry[
                    "pk_values"
                ]
            )
        )

        section = _format_km_values(
            values
        )

        detail = {
            "road": entry[
                "road"
            ],
            "section": section,
            "direction": entry[
                "direction"
            ],
        }

        details.append(
            detail
        )

    return details


# ============================================================
# CONSTRUIR INCIDENCIA FINAL
# ============================================================

def _merge_dgt_into_fire(
    fire,
    dgt_items,
):
    road_details = (
        _merge_dgt_road_details(
            dgt_items
        )
    )

    if not road_details:
        return None

    roads = [
        detail["road"]
        for detail
        in road_details
    ]

    # --------------------------------------------------------
    # MUNICIPIO
    # --------------------------------------------------------

    municipality = fire.get(
        "municipality",
        "No disponible",
    )

    if (
        municipality
        == "No disponible"
    ):

        for item in dgt_items:

            location = normalize(
                item.get(
                    "location_text",
                    "",
                )
            )

            if not location:
                continue

            # Intento conservador:
            # si aparece un municipio ya conocido
            # en la localización DATEX.
            for fire_item in (
                [fire]
            ):

                candidate = normalize(
                    fire_item.get(
                        "municipality",
                        "",
                    )
                )

                if (
                    candidate
                    and candidate
                    != "No disponible"
                    and candidate.lower()
                    in location.lower()
                ):
                    municipality = candidate
                    break

    # --------------------------------------------------------
    # PROVINCIA
    # --------------------------------------------------------

    province = fire.get(
        "province",
        "No disponible",
    )

    if province == "No disponible":

        for item in dgt_items:

            road = normalize_road(
                item.get(
                    "road",
                    "",
                )
            )

            match = re.match(
                r"^([A-Z]{1,5})-\d{1,5}$",
                road,
            )

            if not match:
                continue

            inferred = (
                ROAD_PROVINCES.get(
                    match.group(1)
                )
            )

            if inferred:
                province = inferred
                break

    # --------------------------------------------------------
    # FUENTES INFOCA
    # --------------------------------------------------------

    source_urls = []

    for url in (
        fire.get(
            "source_urls",
            []
        )
        or []
    ):

        if (
            url
            and url not in source_urls
        ):
            source_urls.append(
                url
            )

    source_url = fire.get(
        "source_url",
        "",
    )

    if (
        source_url
        and source_url not in source_urls
    ):
        source_urls.insert(
            0,
            source_url,
        )

    # --------------------------------------------------------
    # IDs DATEX
    # --------------------------------------------------------

    datex_ids = sorted(
        {
            normalize(
                item.get(
                    "datex_id",
                    "",
                )
            )
            for item in dgt_items
            if normalize(
                item.get(
                    "datex_id",
                    "",
                )
            )
        }
    )

    situation_ids = sorted(
        {
            normalize(
                item.get(
                    "situation_id",
                    "",
                )
            )
            for item in dgt_items
            if normalize(
                item.get(
                    "situation_id",
                    "",
                )
            )
        }
    )

    return {
        "fire": fire.get(
            "fire",
            "Incendio forestal",
        ),

        "province": province,

        "municipality": municipality,

        "road": ", ".join(
            roads
        ),

        "roads": roads,

        "road_details": road_details,

        "section": "",

        "direction": "",

        "closure_type": (
            "Total / no especificado"
        ),

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
            "Corte confirmado"
        ),

        "infoca": (
            "Confirmado"
        ),

        "dgt": (
            "Confirmado"
        ),

        "other_sources": (
            " | ".join(
                source_urls
            )
        ),

        "source_urls": source_urls,

        "source_url": (
            source_urls[0]
            if source_urls
            else ""
        ),

        "source_title": fire.get(
            "source_title",
            "",
        ),

        "datex_ids": datex_ids,

        "situation_ids": (
            situation_ids
        ),
    }


# ============================================================
# API PRINCIPAL
# ============================================================

def fetch_official_incidents():
    """
    DETECCIÓN DE CORTES POR INCENDIO

    REGLAS DEFINITIVAS DE ESTA VERSIÓN:

    1. INFOCAR/DGT debe confirmar:
         forestFire / seriousFire
         +
         roadClosed

    2. INFOCA/Junta identifica el incendio.

    3. Una noticia INFOCA/Junta NO crea un corte por sí sola.

    4. El nombre del incendio procede prioritariamente
       del hashtag INFOCA #IIFFNombre.

    5. Se conserva el municipio de INFOCA.

    6. Los PK proceden de DATEX/INFOCAR.

    7. Nunca se utilizan coordenadas como PK.

    8. Las carreteras de otras provincias NO se descartan.

       Ejemplo válido:

           Incendio de Niebla (Huelva)
           HU-3106
           A-493
           SE-6402
           SE-6400

       si forman parte de la misma emergencia.

    9. Si varios registros DATEX pertenecen a la misma
       situation_id, se consideran parte del mismo conjunto.

    10. Las carreteras se agrupan en un único aviso.

    11. Los PK de una misma carretera se consolidan.

    12. INFOCAR/NAP se deduplican.

    13. Se mantiene una expansión geográfica conservadora
        de 35 km para detectar cortes adicionales del mismo
        incendio cuando no comparten situation_id.
    """

    # --------------------------------------------------------
    # 1. CORTES DGT
    # --------------------------------------------------------

    dgt_items = (
        fetch_datex_closures()
    )

    if not dgt_items:
        return []

    # --------------------------------------------------------
    # 2. INCENDIOS INFOCA
    # --------------------------------------------------------

    fires = (
        fetch_infoca_fires()
    )

    if not fires:
        return []

    grouped = {}

    # --------------------------------------------------------
    # 3. VINCULAR CADA INCENDIO CON INFOCAR
    # --------------------------------------------------------

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

        if not direct_matches:
            continue

        matched = (
            _expand_fire_dgt_cluster(
                fire,
                direct_matches,
                dgt_items,
            )
        )

        if not matched:
            continue

        key = (
            normalize(
                fire.get(
                    "fire",
                    "",
                )
            ).lower()
            or (
                normalize(
                    fire.get(
                        "province",
                        "",
                    )
                ).lower()
                + "|"
                + normalize(
                    fire.get(
                        "municipality",
                        "",
                    )
                ).lower()
            )
        )

        if key not in grouped:

            grouped[key] = {
                "fire": fire,
                "dgt": [],
            }

        existing_keys = {
            (
                item.get(
                    "datex_id"
                )
                or (
                    item.get(
                        "situation_id",
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
                        "lat"
                    ),
                    item.get(
                        "lon"
                    ),
                )
            )
            for item
            in grouped[key]["dgt"]
        }

        for item in matched:

            item_key = (
                item.get(
                    "datex_id"
                )
                or (
                    item.get(
                        "situation_id",
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
                        "lat"
                    ),
                    item.get(
                        "lon"
                    ),
                )
            )

            if item_key in existing_keys:
                continue

            grouped[key]["dgt"].append(
                item
            )

            existing_keys.add(
                item_key
            )

    # --------------------------------------------------------
    # 4. CONSTRUIR AVISOS ÚNICOS
    # --------------------------------------------------------

    incidents = []

    for group in grouped.values():

        incident = (
            _merge_dgt_into_fire(
                group["fire"],
                group["dgt"],
            )
        )

        if incident:
            incidents.append(
                incident
            )

    return incidents


# ============================================================
# REAPERTURAS
# ============================================================
#
# NO MODIFICAMOS TODAVÍA LA LÓGICA DE REAPERTURA.
#
# La fase actual queda centrada exclusivamente en dejar
# PERFECTAMENTE RESUELTA la detección y agrupación de cortes.
#
# ============================================================

def fetch_official_reopenings():
    return []
