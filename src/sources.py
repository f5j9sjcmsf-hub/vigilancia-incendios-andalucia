import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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

TIMEZONE = ZoneInfo("Europe/Madrid")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; VigilanciaIncendiosAndalucia/2.0)"
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
    "infoca",
    "plan infoca",
)

ROAD_WORDS = (
    "carretera",
    "carreteras",
    "autovía",
    "autovia",
    "autopista",
    "vía",
    "via",
    "tráfico",
    "trafico",
    "circulación",
    "circulacion",
)

# Expresiones que indican una afectación REAL de circulación.
CLOSURE_PATTERNS = (
    r"\bcortad[ao]s?\b",
    r"\bcerrad[ao]s?\b",
    r"\binterrumpid[ao]s?\b",
    r"\bsin\s+circulaci[oó]n\b",
    r"\bcorte\s+de\s+(?:la\s+)?(?:carretera|tr[aá]fico|circulaci[oó]n)\b",
    r"\bcierre\s+de\s+(?:la\s+)?(?:carretera|tr[aá]fico|circulaci[oó]n)\b",
    r"\brestricci[oó]n\s+(?:de\s+)?circulaci[oó]n\b",
    r"\btr[aá]fico\s+cortado\b",
    r"\bcirculaci[oó]n\s+interrumpida\b",
    r"\bqueda\s+cortad[ao]\b",
    r"\bpermanece\s+cortad[ao]\b",
    r"\bse\s+mantiene\s+cortad[ao]\b",
    r"\bse\s+ha\s+cortado\b",
    r"\bse\s+procede\s+al\s+corte\b",
)

REOPEN_PATTERNS = (
    r"\breabiert[ao]s?\b",
    r"\breapertura\b",
    r"\babiert[ao]\s+al\s+tr[aá]fico\b",
    r"\brestablecida?\s+la\s+circulaci[oó]n\b",
    r"\bse\s+restablece\s+la\s+circulaci[oó]n\b",
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


def now_spain():
    """
    Hora oficial de España peninsular.
    Formato corto HH:MM.
    """
    return datetime.now(TIMEZONE).strftime("%H:%M")


# ============================================================
# PROVINCIAS
# ============================================================

def find_province(text):
    text_lower = text.lower()

    # Primero buscamos coincidencias completas.
    for province in ANDALUSIA_PROVINCES:
        if re.search(
            rf"\b{re.escape(province.lower())}\b",
            text_lower,
        ):
            return province

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

    for alias, province in aliases.items():
        if re.search(
            rf"\b{re.escape(alias)}\b",
            text_lower,
        ):
            return province

    return "No disponible"


# ============================================================
# CARRETERAS
# ============================================================

def extract_roads(text):
    """
    Extrae carreteras reales.

    Evita prefijos vacíos y números sueltos como:
    -112
    -2026
    -061

    Ejemplos válidos:
    A-49
    A-493
    N-435
    HU-3106
    HU-4103
    GR-3201
    MA-8300
    SE-5203
    """

    patterns = [
        # Carreteras estatales:
        r"\b(?:A|AP|N)-\s?\d{1,4}\b",

        # Carreteras provinciales/autonómicas:
        r"\b(?:AL|CA|CO|GR|H|HU|J|JA|MA|SE)-\s?\d{3,5}\b",
    ]

    roads = []

    for pattern in patterns:
        for match in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            road = re.sub(
                r"\s+",
                "",
                match.upper(),
            )

            if road not in roads:
                roads.append(road)

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

        r"\bkilómetro\s+(\d+(?:[.,]\d+)?)",

        r"\bkm\s+(\d+(?:[.,]\d+)?)",

        r"\bPK\s+(\d+(?:[.,]\d+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
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
        "ambos sentidos",
    )

    text_lower = text.lower()

    for direction in directions:

        if direction.lower() in text_lower:

            if direction.lower() == "ambos sentidos":
                return "Ambos sentidos"

            return direction

    return "No disponible"


# ============================================================
# DETECCIÓN DE CORTE REAL
# ============================================================

def has_real_closure(text):
    """
    Comprueba que exista una expresión que realmente indique
    una interrupción de circulación.
    """

    for pattern in CLOSURE_PATTERNS:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            return True

    return False


def has_real_reopening(text):
    for pattern in REOPEN_PATTERNS:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            return True

    return False


def relevant_blocks(soup):
    """
    Obtiene únicamente bloques de contenido del artículo.

    NO utiliza soup.get_text() sobre toda la página porque eso
    mezcla menús, navegación, footer, noticias relacionadas, etc.
    """

    blocks = []

    for tag in soup.find_all(
        [
            "p",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
        ]
    ):

        text = normalize(
            tag.get_text(
                " ",
                strip=True,
            )
        )

        if len(text) < 20:
            continue

        blocks.append(text)

    return blocks


def find_closure_context(blocks):
    """
    Busca el contexto donde realmente aparece el corte.

    Se incluyen bloques vecinos porque algunas publicaciones
    ponen la carretera en un párrafo y el estado del corte
    en el siguiente.
    """

    contexts = []

    for index, block in enumerate(blocks):

        if not has_real_closure(block):
            continue

        start = max(0, index - 1)
        end = min(len(blocks), index + 2)

        context = " ".join(
            blocks[start:end]
        )

        contexts.append(context)

    return contexts


# ============================================================
# MUNICIPIO / INCENDIO
# ============================================================

def extract_municipality(title, text):

    patterns = [
        r"\bincendio\s+(?:forestal\s+)?(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+)",

        r"\bfuego\s+(?:forestal\s+)?(?:en|de)\s+"
        r"([A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            title,
            flags=re.IGNORECASE,
        )

        if match:

            value = normalize(
                match.group(1)
            )

            value = re.split(
                r"\s+(?:pese|provoca|afecta|obliga|ha|y|uno|una)\s+",
                value,
                flags=re.IGNORECASE,
            )[0]

            value = value.strip(
                " ,.-"
            )

            if value:
                return value

    # Buscar municipios conocidos dentro del título/texto.
    # Primero priorizamos los nombres de provincia/localización
    # que aparezcan de forma razonable.
    return "No disponible"


def extract_fire_name(title, municipality):

    title = normalize(title)

    # Eliminamos sufijos editoriales.
    title = re.split(
        r"\s+-\s+(?:Portavoz|Junta|Gobierno|Emergencias|"
        r"Consejería|Andalucía)",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    patterns = [
        r"\bincendio\s+(?:forestal\s+)?(?:en|de)\s+(.+)$",

        r"\bfuego\s+(?:forestal\s+)?(?:en|de)\s+(.+)$",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            title,
            flags=re.IGNORECASE,
        )

        if match:

            value = normalize(
                match.group(1)
            )

            value = re.split(
                r"\s+(?:pese|por|provoca|afecta|obliga|uno|una)\s+",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]

            value = value.strip(
                " ,.-"
            )

            if value:
                return value

    if municipality != "No disponible":
        return municipality

    return "Incendio forestal"


# ============================================================
# FUENTES DE LA JUNTA
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

        if "juntadeandalucia.es" not in href:
            continue

        # Solo usamos enlaces cuyo propio título habla
        # de incendio/incendio forestal.
        if not contains_any(
            title,
            FIRE_KEYWORDS,
        ):
            continue

        candidates.append(
            {
                "title": title,
                "url": href,
            }
        )

    # Duplicados por URL.
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

    # MUY IMPORTANTE:
    # usamos el título del enlace original,
    # no soup.title, que puede contener títulos globales
    # o metadatos de la web.
    title = normalize(
        article["title"]
    )

    blocks = relevant_blocks(
        soup
    )

    if not blocks:
        return None

    article_text = " ".join(
        blocks
    )

    # --------------------------------------------------------
    # Debe existir un incendio REAL
    # --------------------------------------------------------

    if not contains_any(
        title + " " + article_text,
        FIRE_KEYWORDS,
    ):
        return None

    # --------------------------------------------------------
    # Buscar SOLO contextos donde existe un corte real
    # --------------------------------------------------------

    closure_contexts = find_closure_context(
        blocks
    )

    reopening = has_real_reopening(
        article_text
    )

    # --------------------------------------------------------
    # REAPERTURA
    # --------------------------------------------------------

    if reopening and not closure_contexts:

        province = find_province(
            title + " " + article_text
        )

        municipality = extract_municipality(
            title,
            article_text,
        )

        fire_name = extract_fire_name(
            title,
            municipality,
        )

        roads = extract_roads(
            article_text
        )

        if not roads:
            return None

        return {
            "fire": fire_name,
            "province": province,
            "municipality": municipality,
            "road": ", ".join(roads),
            "section": extract_section(
                article_text
            ),
            "direction": extract_direction(
                article_text
            ),
            "reopened_at": now_spain(),
            "source": "Junta de Andalucía",
            "source_url": article["url"],
            "source_title": title,
        }

    # --------------------------------------------------------
    # CORTE
    # --------------------------------------------------------

    if not closure_contexts:
        # Hay incendio pero no un corte real.
        return None

    # Unimos únicamente los contextos donde se ha detectado
    # realmente el corte.
    closure_text = " ".join(
        closure_contexts
    )

    roads = extract_roads(
        closure_text
    )

    if not roads:
        # No podemos demostrar qué carretera está afectada.
        return None

    province = find_province(
        closure_text + " " + title
    )

    if province == "No disponible":
        return None

    municipality = extract_municipality(
        title,
        closure_text,
    )

    fire_name = extract_fire_name(
        title,
        municipality,
    )

    return {
        "fire": fire_name,
        "province": province,
        "municipality": municipality,
        "road": ", ".join(roads),
        "section": extract_section(
            closure_text
        ),
        "direction": extract_direction(
            closure_text
        ),
        "closure_type": "Corte de circulación",
        "detected_at": now_spain(),
        "fire_status": "Incendio forestal confirmado por Junta/INFOCA",
        "infoca": "Junta/INFOCA",
        "dgt": "Pendiente de cotejo DGT",
        "other_sources": "Junta de Andalucía",
        "source_url": article["url"],
        "source_title": title,
    }


# ============================================================
# API UTILIZADA POR main.py
# ============================================================

def fetch_official_incidents():

    incidents = []

    try:
        articles = get_candidate_articles()
    except Exception:
        return []

    for article in articles:

        try:

            result = parse_article(
                article
            )

            if not result:
                continue

            if "closure_type" not in result:
                continue

            incidents.append(
                result
            )

        except Exception:
            # Una noticia problemática no debe detener
            # toda la vigilancia.
            continue

    return incidents


def fetch_official_reopenings():

    reopenings = []

    try:
        articles = get_candidate_articles()
    except Exception:
        return []

    for article in articles:

        try:

            result = parse_article(
                article
            )

            if not result:
                continue

            if "reopened_at" not in result:
                continue

            reopenings.append(
                result
            )

        except Exception:
            continue

    return reopenings
