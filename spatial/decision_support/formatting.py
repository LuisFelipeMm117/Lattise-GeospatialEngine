# spatial/decision_support/formatting.py
"""
Decision Support Engine — formato numérico puro para insights.

Mismo criterio de formato compacto ya usado en
`app/helpers/formatting.py::format_compact/format_pct`, reimplementado
aquí sin ninguna dependencia de `streamlit`/`numpy` más allá de lo
estrictamente necesario, para que `spatial.decision_support.insights`
no dependa de la capa de aplicación (Layer Isolation, Sección 5).
"""
from __future__ import annotations

import math
from typing import Optional


def format_compact(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(float(v))
    if v >= 1_000_000:
        return f"{sign}{v/1_000_000:,.2f}M"
    if v >= 1_000:
        return f"{sign}{v/1_000:,.1f}K"
    return f"{sign}{v:,.0f}"


def format_pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{float(v):.{decimals}f}%"


def short_name(nombre: Optional[str]) -> str:
    """Recorta el prefijo `"Comunidad N — "` de los nombres de cluster
    producidos por `scripts/build_sector_clusters.py::_nombre_cluster`."""
    if nombre is None:
        return "—"
    return str(nombre).split("—", 1)[-1].strip()


__all__ = ["format_compact", "format_pct", "short_name"]
