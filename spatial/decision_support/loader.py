# spatial/decision_support/loader.py
"""
Decision Support Engine — carga de artefactos ya cerrados.

Consumidor puro de las mismas cuatro fuentes que ya usa
`app/helpers/data_sources.py`, sin `streamlit` ni caché de aplicación
(la capa de aplicación decide cómo/cuándo cachear; este módulo solo
sabe leer del disco):

    1. `data/analytics/sector_cluster.json`   (Louvain, offline, congelado)
    2. `spatial.config.WAREHOUSE_PARQUET`     (Stage 5, CERRADO)
    3. `spatial.config.SERIO_SECTORES_CSV`    (catálogo de sectores)
    4. `spatial.simulation.SpatialMatrix.from_gal()` (Stage 8A, CERRADO)

No reconstruye ninguno de estos artefactos — si no existen en disco,
las funciones devuelven `None` explícitamente (nunca uno vacío que
simule datos reales).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from spatial.config import SERIO_SECTORES_CSV, WAREHOUSE_PARQUET
from spatial.decision_support.constants import SECTOR_CLUSTER_JSON

try:
    from spatial.simulation import SpatialMatrix
except ImportError:  # pragma: no cover — spatial.simulation siempre debería existir
    SpatialMatrix = None  # type: ignore[assignment,misc]


def load_cluster_artifact(path: str | Path = SECTOR_CLUSTER_JSON) -> Optional[dict]:
    """Lee el artefacto congelado de comunidades económicas (Louvain).
    Devuelve `None` si no existe — nunca infiere un artefacto vacío."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_warehouse_gdf(path: str | Path = WAREHOUSE_PARQUET) -> Optional[gpd.GeoDataFrame]:
    """Lee `warehouse.parquet` (Stage 5, CERRADO). Devuelve `None` si
    no existe."""
    path = Path(path)
    if not path.exists():
        return None
    return gpd.read_parquet(path)


def load_sector_names(path: str | Path = SERIO_SECTORES_CSV) -> dict:
    """Catálogo código SERIO → nombre. Devuelve `{}` (nunca `None`) si
    el catálogo no existe, para que los `.get(codigo, default)` aguas
    abajo sigan funcionando sin ramas especiales."""
    path = Path(path)
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"scian": str})
    return dict(zip(df["scian"].astype(str), df["nombre"].astype(str)))


def load_spatial_matrix(gal_path: str | Path, metadata_path: Optional[str | Path] = None):
    """Reconstruye `SpatialMatrix` desde `graph.gal` (Stage 8A,
    CERRADO). Devuelve `None` si el `.gal` no existe o si la
    reconstrucción falla (nunca propaga la excepción hacia el reporte
    de decisión — la ausencia de contigüidad espacial es un dato
    legítimo, no un error fatal del Decision Support Engine)."""
    if SpatialMatrix is None:
        return None
    gal_path = Path(gal_path)
    if not gal_path.exists():
        return None
    try:
        return SpatialMatrix.from_gal(gal_path, metadata_path)
    except Exception:
        return None


__all__ = [
    "load_cluster_artifact",
    "load_warehouse_gdf",
    "load_sector_names",
    "load_spatial_matrix",
]
