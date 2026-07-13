# app/helpers/formatting.py
"""
Opportunity Explorer — utilidades de formato y presentación.

Puramente cosmético: ningún dato económico se calcula aquí. Mismas
convenciones ya usadas en `app/pages/1_Run Simulation.py` y
`app/pages/4_Spatial_Cluster_Intelligence.py` (fix de indentación de
Markdown vía `textwrap.dedent().strip()`, `_municipio_code` derivado de
`cvegeo`, formato compacto de magnitudes).
"""
from __future__ import annotations

import textwrap

import numpy as np
import streamlit as st


# ══════════════════════════════════════════════════════════
# Markdown seguro (fix de indentación — mismo patrón ya usado en el resto
# de Lattise Studio: HTML multilínea dentro de funciones indentadas se
# renderiza como bloque de código si no se hace dedent().strip()).
# ══════════════════════════════════════════════════════════
def md(html: str) -> None:
    st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# Identificación territorial derivada de cvegeo (INEGI Marco
# Geoestadístico: cvegeo = entidad(2) + municipio(3) + localidad(4) +
# ageb(4)). No requiere ninguna columna adicional del warehouse.
# ══════════════════════════════════════════════════════════
def municipio_code(cvegeo: str) -> str:
    cvegeo = str(cvegeo)
    return cvegeo[2:5] if len(cvegeo) >= 5 else "—"


def entidad_code(cvegeo: str) -> str:
    cvegeo = str(cvegeo)
    return cvegeo[0:2] if len(cvegeo) >= 2 else "—"


# ══════════════════════════════════════════════════════════
# Formato numérico compacto (idéntico criterio a
# `_format_compact` de Spatial Cluster Intelligence)
# ══════════════════════════════════════════════════════════
def format_compact(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(float(v))
    if v >= 1_000_000:
        return f"{sign}{v/1_000_000:,.2f}M"
    if v >= 1_000:
        return f"{sign}{v/1_000:,.1f}K"
    return f"{sign}{v:,.0f}"


def format_pct(v, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{float(v):.{decimals}f}%"


def short_name(nombre: str) -> str:
    return str(nombre).split("—", 1)[-1].strip()


# ══════════════════════════════════════════════════════════
# Paleta compartida — misma paleta categórica usada en Spatial Cluster
# Intelligence, para que un cluster se vea del mismo color en ambas
# páginas.
# ══════════════════════════════════════════════════════════
PALETTE = [
    "#5B8DEF", "#34D399", "#F5B942", "#F87171", "#A78BFA", "#22D3EE",
    "#FB923C", "#4ADE80", "#F472B6", "#818CF8", "#FACC15", "#2DD4BF",
    "#FCA5A5", "#93C5FD", "#C4B5FD", "#6EE7B7", "#FDBA74", "#E879F9",
    "#67E8F9", "#BEF264",
]


def color_for_index(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


def color_for_hash(key) -> str:
    """Color determinístico para claves sin orden natural (p. ej. código
    de sector SCIAN/SERIO) — mismo color siempre para la misma clave,
    sin depender de cuántas claves distintas haya en pantalla."""
    return PALETTE[hash(str(key)) % len(PALETTE)]
