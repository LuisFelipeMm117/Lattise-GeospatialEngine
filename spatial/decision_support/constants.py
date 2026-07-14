# spatial/decision_support/constants.py
"""
Decision Support Engine — constantes de columnas y rutas por defecto.

Mismo criterio de "Single Source of Truth" ya usado en
`spatial.warehouse.builder` (`SECTOR_COL`, `EMPLEO_COL`),
`spatial.allocation.serio_bridge` (`DEFAULT_SECTOR_COL`,
`DEFAULT_DELTA_COL`) y `spatial.simulation.engine`
(`IMPACTO_DIRECTO_COL`, ...): un único lugar declara los nombres de
columna que el resto del paquete importa, en vez de repetir literales.

Este módulo NO define ninguna ruta nueva bajo `spatial/config.py` (ese
archivo está congelado — Sección "ARQUITECTURA" del encargo). Reutiliza
`spatial.config.DATA_DIR` como base, exactamente igual que
`scripts/build_sector_clusters.py` reutiliza `DATA_DIR` para resolver
`data/analytics/sector_cluster.json` sin tocar `config.py`.
"""
from __future__ import annotations

from spatial.config import AGEB_ID_COL, DATA_DIR
from spatial.warehouse.builder import SECTOR_COL

# ── Columnas heredadas de artefactos ya cerrados (solo se reimportan aquí
#    para que el resto de decision_support/ tenga un único punto de
#    importación; no se redefinen valores distintos) ───────────────────────
ID_COL = AGEB_ID_COL              # "cvegeo"
SECTOR_SERIO_COL = SECTOR_COL     # "sector_serio"

# Columnas producidas por spatial.simulation.engine (Stage 8C, CERRADO).
# Se repiten aquí como strings — nunca se importa `spatial.simulation.engine`
# en tiempo de import porque `simulation_gdf` es un insumo OPCIONAL (puede no
# existir si el usuario nunca corrió "Run Simulation"); ver
# `spatial.decision_support.report.build_decision_support_report`.
IMPACTO_DIRECTO_COL = "shock_directo"
IMPACTO_PROPAGADO_COL = "impacto_propagado"
IMPACTO_INDIRECTO_COL = "impacto_indirecto"
ES_ISLA_COL = "es_isla"

# ── Columnas nuevas, propias de este paquete (perfiles/agregaciones) ───────
MUNICIPIO_COL = "municipio"
ENTIDAD_COL = "entidad"
CLUSTER_ID_COL = "cluster_id"
PESO_COL = "peso"
PESO_METODO_COL = "peso_metodo"
PARTICIPACION_PCT_COL = "participacion_pct"
RANKING_COL = "ranking"

PESO_METODO_EMPLEO = "empleo"
PESO_METODO_ESTABLECIMIENTOS = "establecimientos"

# ── Rutas del artefacto congelado de comunidades económicas (Louvain) ──────
# Mismo archivo que ya consume `app/helpers/data_sources.py::load_cluster_artifact`
# y que produce `scripts/build_sector_clusters.py` — solo lectura.
ANALYTICS_DIR = DATA_DIR / "analytics"
SECTOR_CLUSTER_JSON = ANALYTICS_DIR / "sector_cluster.json"

# ── Directorio de salida propio de este paquete (nuevo, no congelado) ──────
# Artefactos que EL PROPIO Decision Support Engine puede serializar
# (`DecisionSupportReport.to_json/to_parquet`) — nunca insumos.
DECISION_SUPPORT_DIR = DATA_DIR / "decision_support"

__all__ = [
    "ID_COL",
    "SECTOR_SERIO_COL",
    "IMPACTO_DIRECTO_COL",
    "IMPACTO_PROPAGADO_COL",
    "IMPACTO_INDIRECTO_COL",
    "ES_ISLA_COL",
    "MUNICIPIO_COL",
    "ENTIDAD_COL",
    "CLUSTER_ID_COL",
    "PESO_COL",
    "PESO_METODO_COL",
    "PARTICIPACION_PCT_COL",
    "RANKING_COL",
    "PESO_METODO_EMPLEO",
    "PESO_METODO_ESTABLECIMIENTOS",
    "ANALYTICS_DIR",
    "SECTOR_CLUSTER_JSON",
    "DECISION_SUPPORT_DIR",
]
