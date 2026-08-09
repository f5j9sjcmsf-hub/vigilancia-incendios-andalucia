import re
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


# ============================================================
# PALABRAS CLAVE
# ============================================================

FIRE_KEYWORDS = (
    "incendio forestal",
    "incendio",
    "plan infoca",
    "infoca",
    "fuego forestal",
)

ROAD_KEYWORDS = (
    "carretera",
    "carreteras",
    "autovía",
    "autovia",
    "autopista",
    "vía",
    "trafico",
    "tráfico",
    "circulación",
    "circulacion",
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


def find_province(text):
    text_lower = text.lower()

    for province in ANDALUSIA_PROVINCES:
        if province.lower() in text_lower:
            return province

    # Casos habituales
    aliases = {
        "almeria": "Almería",
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

    for alias, province in aliases.items():
        if alias in text_lower:
            return province

    return "No disponible"


def extract_road(text):
    """
    Busca identificadores habituales de carreteras andaluzas.

    Ejemplos:
    A-7
    A-92
    A-44
    N-340
    MA-8300
    AL-6109
    GR-3201
    CA-9101
    SE-5203
    CO-7409
    JA-xxxx
    """

    pattern = re.compile(
        r"\b("
        r"A|AP|N|"
        r"AL|CA|CO|GR|H|HU|J|JA|MA|SE|"
        r"AB|EX|"
        r""
        r")-?\s?(\d{3,5})\b",
        re.IGNORECASE,
    )

    matches = pattern.findall(text)

    if not matches:
        return "No disponible"

    roads = []

    for prefix, number in matches:
        road = f"{prefix.upper()}-{number}"

        if road not in roads:
            roads.append(road)

    return ", ".join(roads)


def extract_section(text):
    """
    Extrae tramos expresados mediante kilómetros.
    """

    patterns = [
        r"(?:entre|del)\s+(?:los\s+)?(?:PK|puntos kilométricos?)\s*"
        r"(\d+(?:[.,]\d+)?)\s*(?:y|al)\s*(\d+(?:[.,]\d+)?)",

        r"(?:entre|del)\s+(?:los\s+)?kilómetros?\s*"
        r"(\d+(?:[.,]\d+)?)\s*(?:y|al)\s*(\d+(?:[.,]\d+)?)",

        r"kilómetro\s+(\d+(?:[.,]\d+)?)",
        r"km\s+(\d+(?:[.,]\d+)?)",
        r"PK\s+(\d+(?:[.,]\d+)?)",
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
    )

    for direction in directions:
        if direction.lower() in text.lower():
            return direction

    if "ambos sentidos" in text.lower():
        return "Ambos sentidos"

    return "No disponible"


def extract_municipality(title, text):
    """
    Intenta obtener el municipio desde el título.
    Si no es posible, devuelve No disponible.
    """

    # Patrones habituales de titulares de la Junta.
    patterns = [
        r"incendio\s+(?:en|de)\s+([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+)",
        r"fuego\s+(?:en|de)\s+([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            title,
            re.IGNORECASE,
        )

        if match:
            value = normalize(match.group(1))

            value = re.split(
                r"\s+(?:obliga|provoca|afecta|ha|y)\s+",
                value,
                flags=re.IGNORECASE,
            )[0]

            return value.strip(" ,.-")

    return "No disponible"


def extract_fire_name(title):
    title = normalize(title)

    match = re.search(
        r"incendio\s+(?:en|de)\s+(.+?)(?:\s+-\s+|\s+por\s+|\s*$)",
        title,
        re.IGNORECASE,
    )

    if match:
        return normalize(match.group(1))

    match = re.search(
        r"fuego\s+(?:en|de)\s+(.+?)(?:\s+-\s+|\s+por\s+|\s*$)",
        title,
        re.IGNORECASE,
    )

    if match:
        return normalize(match.group(1))

    return title


# ============================================================
# DETECCIÓN DE ARTÍCULOS OFICIALES
# ============================================================

def get_candidate_articles():
    """
    Obtiene enlaces de publicaciones de la Junta/EMA/112
    relacionados con incendios y emergencias.

    No utiliza prensa privada.
    """

    response = get(JUNTA_SEARCH_URL)

    soup = BeautifulSoup(
        response.text,
        "lxml",
    )

    candidates = []

    for link in soup.find_all("a", href=True):
        title = normalize(link.get_text(" ", strip=True))
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

    # Elimina duplicados
    unique = {}

    for item in candidates:
        unique[item["url"]] = item

    return list(unique.values())


def parse_article(article):
    """
    Analiza una publicación oficial y determina si existe
    una relación explícita incendio forestal -> carretera cortada.
    """

    response = get(article["url"])

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

    # Debe existir incendio.
    if not contains_any(
        full_text,
        FIRE_KEYWORDS,
    ):
        return None

    # Debe existir carretera/vía.
    if not contains_any(
        full_text,
        ROAD_KEYWORDS,
    ):
        return None

    # Debe existir corte/restricción.
    has_closure = contains_any(
        full_text,
        CLOSURE_KEYWORDS,
    )

    has_reopening = contains_any(
        full_text,
        REOPEN_KEYWORDS,
    )

    if not has_closure and not has_reopening:
        return None

    province = find_province(full_text)

    if province == "No disponible":
        return None

    road = extract_road(full_text)

    if road == "No disponible":
        return None

    municipality = extract_municipality(
        title,
        full_text,
    )

    fire_name = extract_fire_name(title)

    section = extract_section(full_text)

    direction = extract_direction(full_text)

    detected_at = datetime.now(
        timezone.utc
    ).isoformat()

    if has_closure and not has_reopening:
        closure_type = "Total / no especificado"

        return {
            "fire": fire_name,
            "province": province,
            "municipality": municipality,
            "road": road,
            "section": section,
            "direction": direction,
            "closure_type": closure_type,
            "detected_at": detected_at,
            "fire_status": "Incendio forestal confirmado por fuente oficial",
            "infoca": "Información oficial Junta/EMA/INFOCA",
            "dgt": "Pendiente de cotejo DGT",
            "other_sources": article["url"],
            "source_url": article["url"],
            "source_title": title,
        }

    return {
        "fire": fire_name,
        "province": province,
        "municipality": municipality,
        "road": road,
        "section": section,
        "direction": direction,
        "reopened_at": detected_at,
        "source": article["url"],
        "source_title": title,
    }


# ============================================================
# API UTILIZADA POR main.py
# ============================================================

def fetch_official_incidents():
    """
    Devuelve únicamente cortes que aparecen en publicaciones
    oficiales de la Junta/EMA/112 y que contienen:

        incendio + carretera + corte

    No genera alertas por incendios sin afección viaria.
    """

    incidents = []

    try:
        articles = get_candidate_articles()
    except Exception:
        return []

    for article in articles:
        try:
            result = parse_article(article)

            if not result:
                continue

            # Una reapertura no es un nuevo corte.
            if "closure_type" not in result:
                continue

            incidents.append(result)

        except Exception:
            # Una publicación problemática no debe detener
            # toda la vigilancia.
            continue

    return incidents


def fetch_official_reopenings():
    """
    Devuelve únicamente reaperturas expresamente mencionadas
    en publicaciones oficiales.
    """

    reopenings = []

    try:
        articles = get_candidate_articles()
    except Exception:
        return []

    for article in articles:
        try:
            result = parse_article(article)

            if not result:
                continue

            if "reopened_at" not in result:
                continue

            reopenings.append(result)

        except Exception:
            continue

    return reopenings
