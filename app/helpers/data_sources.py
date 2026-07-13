# app/helpers/data_sources.py
"""
Opportunity Explorer — capa de carga de datos.

Consumidor puro de artefactos YA CERRADOS. No reconstruye Warehouse
(Stage 5), Spatial Graph, Louvain (`scripts/build_sector_clusters.py`)
ni ninguna simulación. Mismas tres fuentes que ya usa
`app/pages/4_Spatial_Cluster_Intelligence.py`:

    1. data/analytics/sector_cluster.json   (Louvain, offline, congelado)
    2. spatial.config.WAREHOUSE_PARQUET     (Stage 5, CERRADO)
    3. st.session_state["simulation_gdf"/"simulation_report"]
       (Stage 8C, producido por Run Simulation — OPCIONAL)

Se agrega una cuarta fuente de solo lectura, también ya cerrada:

    4. spatial.simulation.SpatialMatrix.from_gal()  (Stage 8A, CERRADO)
       — usada únicamente para listar AGEBs vecinas (contigüidad
       espacial ya calculada), nunca para recalcular pesos ni ρ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spatial.config import (  # noqa: E402
    AGEB_ID_COL,
    DATA_DIR,
    GRAPH_GAL_PATH,
    GRAPH_METADATA_JSON,
    SERIO_SECTORES_CSV,
    WAREHOUSE_PARQUET,
)
from spatial.warehouse.builder import SECTOR_COL  # noqa: E402 — solo el nombre de columna

try:
    from spatial.simulation.engine import (  # noqa: E402
        IMPACTO_DIRECTO_COL,
        IMPACTO_INDIRECTO_COL,
        IMPACTO_PROPAGADO_COL,
    )
except ImportError:  # pragma: no cover
    IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL = (
        "shock_directo", "impacto_indirecto", "impacto_propagado",
    )

try:
    from spatial.simulation import SpatialMatrix
except ImportError:  # pragma: no cover
    SpatialMatrix = None  # type: ignore[assignment,misc]

SECTOR_CLUSTER_JSON = DATA_DIR / "analytics" / "sector_cluster.json"

SIM_COLS = [AGEB_ID_COL, IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]


# ══════════════════════════════════════════════════════════
# 1. Artefacto de comunidades económicas (Louvain, congelado)
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def load_cluster_artifact() -> Optional[dict]:
    if not SECTOR_CLUSTER_JSON.exists():
        return None
    with open(SECTOR_CLUSTER_JSON, encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════
# 2. Warehouse espacial (Stage 5, CERRADO) — una fila por (AGEB, sector)
# ══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="Loading spatial warehouse…")
def load_warehouse_gdf() -> Optional[gpd.GeoDataFrame]:
    if not Path(WAREHOUSE_PARQUET).exists():
        return None
    return gpd.read_parquet(WAREHOUSE_PARQUET)


# ══════════════════════════════════════════════════════════
# 3. Catálogo de sectores SERIO (código → nombre) — activo congelado,
#    mismo archivo que usa `serio/loader.py`.
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def load_sector_names() -> dict:
    if not Path(SERIO_SECTORES_CSV).exists():
        return {}
    df = pd.read_csv(SERIO_SECTORES_CSV, dtype={"scian": str})
    return dict(zip(df["scian"].astype(str), df["nombre"].astype(str)))


# ══════════════════════════════════════════════════════════
# 4. Simulación cargada en Run Simulation (OPCIONAL, solo lectura de
#    session_state — nunca se ejecuta una simulación desde aquí).
# ══════════════════════════════════════════════════════════
def get_simulation_gdf() -> Optional[gpd.GeoDataFrame]:
    if "simulation_gdf" not in st.session_state or "simulation_report" not in st.session_state:
        return None
    sim_gdf = st.session_state["simulation_gdf"]
    if any(c not in sim_gdf.columns for c in SIM_COLS):
        return None
    return sim_gdf


def get_simulation_scenario() -> Optional[dict]:
    return st.session_state.get("simulation_scenario")


# ══════════════════════════════════════════════════════════
# 5. Matriz espacial (Stage 8A, CERRADO) — solo para listar vecinos ya
#    calculados por el Spatial Graph Builder. Nunca se recalcula W ni
#    se invoca el operador de propagación desde aquí.
# ══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def load_spatial_matrix():
    if SpatialMatrix is None or not Path(GRAPH_GAL_PATH).exists():
        return None
    try:
        return SpatialMatrix.from_gal(GRAPH_GAL_PATH, GRAPH_METADATA_JSON)
    except Exception:
        return None


def neighbors_of(cvegeo: str) -> list[str]:
    """Vecinos de contigüidad espacial ya calculados (Spatial Graph
    Builder, CERRADO). Devuelve lista vacía si el grafo no está
    disponible o si el AGEB no pertenece a la matriz — nunca se infiere
    vecindad por proximidad geométrica ad hoc en esta capa."""
    sm = load_spatial_matrix()
    if sm is None:
        return []
    try:
        return list(sm.neighbors_of(cvegeo))
    except KeyError:
        return []
