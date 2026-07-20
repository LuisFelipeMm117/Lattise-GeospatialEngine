# api/state.py
"""
Stage 10 — Estado del motor para la API REST.

`EngineState` es el punto único de dependency injection de la API: cada
endpoint recibe una instancia (por defecto, un singleton de proceso) en
vez de importar y cachear artefactos por su cuenta. Esto permite
inyectar un `EngineState` distinto en tests (apuntando a fixtures) sin
tocar las rutas.

Espejo deliberado de `app/helpers/data_sources.py` — mismas fuentes,
mismos artefactos, mismo principio de solo lectura — pero sin ninguna
dependencia de `streamlit` (la API debe poder correr sin un proceso de
Streamlit vivo). Si alguna vez estos dos módulos divergen en qué
artefacto leen o desde qué ruta, es un bug: ambos deben apuntar
exactamente a `spatial.config`.

Nada en este módulo recalcula Warehouse, Spatial Graph, Louvain,
SERIO ni ninguna simulación — todo lo que expone ya fue calculado por
un stage cerrado y vive en disco.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spatial.config import (  # noqa: E402
    DATA_DIR,
    GRAPH_GAL_PATH,
    GRAPH_METADATA_JSON,
    SERIO_SECTORES_CSV,
    WAREHOUSE_PARQUET,
)
from serio.loader import ModeloEconomico  # noqa: E402
from spatial.decision_support.report import (  # noqa: E402
    DecisionSupportReport,
    build_decision_support_report,
)

try:
    from spatial.simulation import SpatialMatrix
except ImportError:  # pragma: no cover
    SpatialMatrix = None  # type: ignore[assignment,misc]

SECTOR_CLUSTER_JSON = DATA_DIR / "analytics" / "sector_cluster.json"
SERIO_DATA_DIR = _REPO_ROOT / "serio" / "data"


class EngineState:
    """Carga perezosa (una sola vez por instancia) de los artefactos
    congelados que necesita la API. Cada propiedad se calcula al primer
    acceso y se cachea en memoria — equivalente en espíritu a
    `st.cache_resource`/`st.cache_data`, pero como atributos de
    instancia, para poder tener un `EngineState` de test aislado del de
    producción sin pisar ningún caché global de Streamlit.
    """

    def __init__(
        self,
        serio_data_dir: Path = SERIO_DATA_DIR,
        warehouse_parquet: Path = WAREHOUSE_PARQUET,
        sector_cluster_json: Path = SECTOR_CLUSTER_JSON,
        sectores_csv: Path = SERIO_SECTORES_CSV,
        gal_path: Path = GRAPH_GAL_PATH,
        metadata_path: Path = GRAPH_METADATA_JSON,
    ) -> None:
        self._serio_data_dir = serio_data_dir
        self._warehouse_parquet = warehouse_parquet
        self._sector_cluster_json = sector_cluster_json
        self._sectores_csv = sectores_csv
        self._gal_path = gal_path
        self._metadata_path = metadata_path

        self._modelo: Optional[ModeloEconomico] = None
        self._cluster_artifact: Optional[dict] = None
        self._warehouse_gdf: Optional[gpd.GeoDataFrame] = None
        self._sector_names: Optional[dict] = None
        self._spatial_matrix = None
        self._decision_report_base: Optional[DecisionSupportReport] = None

    # ── serio/loader.py — modelo Insumo-Producto nacional, CERRADO ────────
    @property
    def modelo(self) -> ModeloEconomico:
        if self._modelo is None:
            self._modelo = ModeloEconomico(str(self._serio_data_dir))
        return self._modelo

    # ── data/analytics/sector_cluster.json — Louvain, offline, congelado ──
    @property
    def cluster_artifact(self) -> Optional[dict]:
        if self._cluster_artifact is None and self._sector_cluster_json.exists():
            with open(self._sector_cluster_json, encoding="utf-8") as f:
                self._cluster_artifact = json.load(f)
        return self._cluster_artifact

    # ── Stage 5, CERRADO ────────────────────────────────────────────────
    @property
    def warehouse_gdf(self) -> Optional[gpd.GeoDataFrame]:
        if self._warehouse_gdf is None and Path(self._warehouse_parquet).exists():
            self._warehouse_gdf = gpd.read_parquet(self._warehouse_parquet)
        return self._warehouse_gdf

    # ── Catálogo de sectores SERIO ──────────────────────────────────────
    @property
    def sector_names(self) -> dict:
        if self._sector_names is None:
            if Path(self._sectores_csv).exists():
                df = pd.read_csv(self._sectores_csv, dtype={"scian": str})
                self._sector_names = dict(zip(df["scian"].astype(str), df["nombre"].astype(str)))
            else:
                self._sector_names = {}
        return self._sector_names

    # ── Stage 8A, CERRADO ───────────────────────────────────────────────
    @property
    def spatial_matrix(self):
        if self._spatial_matrix is None and SpatialMatrix is not None and Path(self._gal_path).exists():
            try:
                self._spatial_matrix = SpatialMatrix.from_gal(self._gal_path, self._metadata_path)
            except Exception:
                self._spatial_matrix = None
        return self._spatial_matrix

    # ── Decision Support Engine, CERRADO — reporte SIN simulación ──────
    def decision_report(self, simulation_gdf: Optional[gpd.GeoDataFrame] = None) -> Optional[DecisionSupportReport]:
        """Reporte de Decision Support. Si `simulation_gdf` es `None`,
        cachea y reutiliza el reporte base (sin impacto de shock) — el
        caso más pedido por la API. Si se pasa `simulation_gdf`, se
        construye uno nuevo sin cachear (depende de la simulación que
        haya corrido el caller, no es un artefacto estable)."""
        if self.warehouse_gdf is None or self.cluster_artifact is None:
            return None
        if simulation_gdf is not None:
            return build_decision_support_report(
                self.warehouse_gdf, self.cluster_artifact, self.sector_names,
                spatial_matrix=self.spatial_matrix, simulation_gdf=simulation_gdf,
            )
        if self._decision_report_base is None:
            self._decision_report_base = build_decision_support_report(
                self.warehouse_gdf, self.cluster_artifact, self.sector_names,
                spatial_matrix=self.spatial_matrix,
            )
        return self._decision_report_base

    def readiness(self) -> dict:
        """Qué artefactos están disponibles ahora mismo — usado por
        `/health`. Nunca intenta regenerar nada que falte."""
        return {
            "modelo_serio": self._serio_data_dir.exists(),
            "warehouse": Path(self._warehouse_parquet).exists(),
            "sector_cluster": self._sector_cluster_json.exists(),
            "spatial_matrix": Path(self._gal_path).exists(),
        }


__all__ = ["EngineState"]
