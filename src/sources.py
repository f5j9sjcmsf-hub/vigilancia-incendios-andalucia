"""
Fuentes oficiales de vigilancia.

Este módulo debe devolver únicamente incidencias respaldadas
por fuentes oficiales y relacionadas causalmente con incendios
forestales.

Fuentes previstas:
- DGT
- INFOCA / Junta de Andalucía
- Emergencias 112 Andalucía
- Organismos titulares de carreteras
"""


def fetch_official_incidents():
    """
    Devuelve una lista de nuevos cortes de carretera confirmados.

    Cada incidencia deberá contener, cuando esté disponible:

    fire
    province
    municipality
    road
    section
    direction
    closure_type
    detected_at
    fire_status
    infoca
    dgt
    other_sources
    """

    # Todavía no consultar fuentes.
    # Las incorporaremos después de verificarlas.
    return []


def fetch_official_reopenings():
    """
    Devuelve una lista de reaperturas confirmadas oficialmente.

    No debe considerarse una carretera reabierta simplemente
    porque desaparezca de una fuente.
    """

    return []
