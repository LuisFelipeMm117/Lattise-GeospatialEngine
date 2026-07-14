# spatial/decision_support/territory.py
"""
Identificación territorial derivada de `cvegeo` (INEGI Marco
Geoestadístico: cvegeo = entidad(2) + municipio(3) + localidad(4) +
ageb(4)).

Estas dos funciones son deliberadamente triviales y puras (ninguna
columna adicional, ningún I/O, ningún estado): es exactamente el mismo
criterio ya usado en `app/helpers/formatting.py::municipio_code` /
`entidad_code`, reimplementado aquí para que `spatial/decision_support`
no dependa de `app/` (la capa de aplicación depende del motor, nunca al
revés — mismo principio de Layer Isolation de toda la Sección 5 de la
especificación formal).
"""
from __future__ import annotations

UNKNOWN_TERRITORY = "—"


def municipio_code(cvegeo) -> str:
    """Segmento de municipio (posiciones 2:5) de un `cvegeo` INEGI.

    Devuelve `UNKNOWN_TERRITORY` explícitamente (nunca infiere ni
    trunca a otra longitud) cuando `cvegeo` es más corto que lo que
    exige el Marco Geoestadístico — nunca se descarta la fila que lo
    contiene, solo queda etiquetada como territorio desconocido.
    """
    s = str(cvegeo)
    return s[2:5] if len(s) >= 5 else UNKNOWN_TERRITORY


def entidad_code(cvegeo) -> str:
    """Segmento de entidad federativa (posiciones 0:2) de un `cvegeo`."""
    s = str(cvegeo)
    return s[0:2] if len(s) >= 2 else UNKNOWN_TERRITORY


__all__ = ["UNKNOWN_TERRITORY", "municipio_code", "entidad_code"]
