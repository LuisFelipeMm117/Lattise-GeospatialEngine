# spatial/decision_support/aggregation.py
"""
Decision Support Engine — Capa de agregación (organización pura de lo
que YA existe en `warehouse.parquet` + `sector_cluster.json`).

Responsabilidad:
    Ninguna función de este archivo reinvierte una matriz, vuelve a
    correr Louvain, recalcula la propagación espacial o el shock.
    Todo es groupby/argmax/merge de organización sobre columnas que
    YA existen en:

        - `warehouse.parquet` (Stage 5, CERRADO) — una fila por
          (AGEB, sector_serio), columnas `n_establecimientos`,
          `empleo_total`.
        - `sector_cluster.json` (Louvain, congelado offline —
          `scripts/build_sector_clusters.py`).

Mismo criterio de peso ya establecido en
`app/pages/4_Spatial_Cluster_Intelligence.py::_ageb_cluster_weights` /
`app/helpers/aggregation.py`: peso = empleo_total si el AGEB tiene
empleo registrado en algún sector, si no, n_establecimientos (respaldo
explícito, `peso_metodo` queda etiquetado por AGEB — nunca se descarta
en silencio).

A diferencia de `app/helpers/aggregation.py`, este módulo:
    - No importa `streamlit` ni usa `@st.cache_data` — es un
      componente puro del backend (`spatial/`), reutilizable desde
      cualquier capa de aplicación o desde pruebas.
    - No importa nada de `app/` — Layer Isolation (Sección 5).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from spatial.decision_support.constants import (
    CLUSTER_ID_COL,
    ID_COL,
    MUNICIPIO_COL,
    PARTICIPACION_PCT_COL,
    PESO_COL,
    PESO_METODO_COL,
    PESO_METODO_EMPLEO,
    PESO_METODO_ESTABLECIMIENTOS,
    RANKING_COL,
    SECTOR_SERIO_COL,
)
from spatial.decision_support.territory import municipio_code


@dataclass
class AggregationReport:
    """Trazabilidad de la agregación AGEB × sector / AGEB × comunidad —
    mismo patrón `to_dict()` que el resto del motor (`AllocationReport`,
    `SpatialMatrixReport`, ...)."""
    n_sectores_en_warehouse: int = 0
    n_registros_sector_no_mapeado: int = 0
    sectores_no_mapeados: list = field(default_factory=list)
    n_agebs_total: int = 0
    n_agebs_con_perfil: int = 0
    n_agebs_sin_perfil: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════
# Peso por (AGEB, sector) — respaldo empleo → establecimientos, calculado a
# nivel AGEB (no a nivel fila) para no mezclar métodos dentro del mismo AGEB.
# ══════════════════════════════════════════════════════════════════════════
def _weighted_long(warehouse_gdf: gpd.GeoDataFrame, id_col: str, sector_col: str) -> pd.DataFrame:
    df = pd.DataFrame(warehouse_gdf.drop(columns="geometry"))
    df[sector_col] = df[sector_col].astype(str)

    emp_by_ageb = df.groupby(id_col)["empleo_total"].sum()
    usa_empleo = emp_by_ageb[emp_by_ageb > 0].index
    df[PESO_COL] = np.where(
        df[id_col].isin(usa_empleo), df["empleo_total"], df["n_establecimientos"]
    )
    df[PESO_METODO_COL] = np.where(
        df[id_col].isin(usa_empleo), PESO_METODO_EMPLEO, PESO_METODO_ESTABLECIMIENTOS
    )
    return df


def ageb_sector_weights(
    warehouse_gdf: gpd.GeoDataFrame, id_col: str = ID_COL, sector_col: str = SECTOR_SERIO_COL
) -> pd.DataFrame:
    """AGEB × sector (peso) — para "sector dominante" y cobertura sectorial."""
    df = _weighted_long(warehouse_gdf, id_col, sector_col)
    return df.groupby([id_col, sector_col, PESO_METODO_COL], as_index=False)[PESO_COL].sum()


def ageb_cluster_weights(
    warehouse_gdf: gpd.GeoDataFrame,
    cluster_artifact: dict,
    id_col: str = ID_COL,
    sector_col: str = SECTOR_SERIO_COL,
) -> tuple[pd.DataFrame, AggregationReport]:
    """AGEB × comunidad económica (peso) — mismo criterio que Spatial
    Cluster Intelligence (`_ageb_cluster_weights`). Sectores del
    warehouse sin mapeo en `sector_to_cluster` (artefacto Louvain) se
    excluyen del agregado y se reportan explícitamente, nunca se
    infiere una comunidad."""
    sector_to_cluster = cluster_artifact.get("sector_to_cluster", {})
    df = _weighted_long(warehouse_gdf, id_col, sector_col)

    mapeados_mask = df[sector_col].isin(sector_to_cluster.keys())
    n_no_mapeados = int((~mapeados_mask).sum())
    sectores_no_mapeados = sorted(df.loc[~mapeados_mask, sector_col].unique().tolist())
    df_mapeado = df.loc[mapeados_mask].copy()
    df_mapeado[CLUSTER_ID_COL] = df_mapeado[sector_col].map(sector_to_cluster).astype(int)

    long_cluster = df_mapeado.groupby(
        [id_col, CLUSTER_ID_COL, PESO_METODO_COL], as_index=False
    )[PESO_COL].sum()

    report = AggregationReport(
        n_sectores_en_warehouse=int(df[sector_col].nunique()),
        n_registros_sector_no_mapeado=n_no_mapeados,
        sectores_no_mapeados=sectores_no_mapeados,
    )
    return long_cluster, report


# ══════════════════════════════════════════════════════════════════════════
# Universo de AGEB — un renglón por AGEB: comunidad dominante, sector
# dominante, peso, municipio, cobertura sectorial, participación, ranking.
# ══════════════════════════════════════════════════════════════════════════
def build_ageb_universe(
    warehouse_gdf: gpd.GeoDataFrame,
    cluster_artifact: dict,
    sector_names: dict,
    id_col: str = ID_COL,
    sector_col: str = SECTOR_SERIO_COL,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, AggregationReport]:
    """Devuelve `(ageb_gdf, long_cluster_df, long_sector_df, report)`.

    `ageb_gdf` — una fila por AGEB:
        cvegeo, geometry, municipio,
        cluster_id, cluster_peso, peso_metodo,
        sector_dominante, sector_dominante_nombre, sector_peso,
        peso_total_ageb, n_sectores_ageb, participacion_pct,
        ranking (1 = mayor peso_total_ageb del territorio).

    AGEBs cuyos únicos sectores quedaron sin mapeo Louvain no reciben
    fila en `ageb_gdf` (no se les puede asignar comunidad dominante) —
    se cuentan explícitamente en `report.n_agebs_sin_perfil`, nunca se
    fuerzan a una comunidad arbitraria.
    """
    long_cluster, report = ageb_cluster_weights(warehouse_gdf, cluster_artifact, id_col, sector_col)
    long_sector = ageb_sector_weights(warehouse_gdf, id_col, sector_col)

    # ── Comunidad dominante por AGEB (argmax peso) ─────────────────────
    if long_cluster.empty:
        dom_cluster = pd.DataFrame(columns=[id_col, CLUSTER_ID_COL, "cluster_peso", PESO_METODO_COL])
    else:
        idx_dom_cl = long_cluster.groupby(id_col)[PESO_COL].idxmax()
        dom_cluster = long_cluster.loc[idx_dom_cl].reset_index(drop=True).rename(
            columns={PESO_COL: "cluster_peso"}
        )

    # ── Sector dominante por AGEB (argmax peso, granularidad sector) ──
    idx_dom_sec = long_sector.groupby(id_col)[PESO_COL].idxmax()
    dom_sector = long_sector.loc[idx_dom_sec].reset_index(drop=True).rename(
        columns={sector_col: "sector_dominante", PESO_COL: "sector_peso"}
    )
    dom_sector["sector_dominante_nombre"] = dom_sector["sector_dominante"].map(
        lambda s: sector_names.get(str(s), f"Sector {s}")
    )

    peso_total_ageb = long_sector.groupby(id_col, as_index=False)[PESO_COL].sum().rename(
        columns={PESO_COL: "peso_total_ageb"}
    )
    n_sectores_ageb = long_sector.groupby(id_col, as_index=False)[sector_col].nunique().rename(
        columns={sector_col: "n_sectores_ageb"}
    )

    perfil = (
        dom_cluster[[id_col, CLUSTER_ID_COL, "cluster_peso", PESO_METODO_COL]]
        .merge(
            dom_sector[[id_col, "sector_dominante", "sector_dominante_nombre", "sector_peso"]],
            on=id_col, how="inner",
        )
        .merge(peso_total_ageb, on=id_col, how="left")
        .merge(n_sectores_ageb, on=id_col, how="left")
    )
    perfil[MUNICIPIO_COL] = perfil[id_col].map(municipio_code)

    peso_total_global = perfil["peso_total_ageb"].sum()
    perfil[PARTICIPACION_PCT_COL] = (
        perfil["peso_total_ageb"] / peso_total_global * 100 if peso_total_global else 0.0
    )
    perfil = perfil.sort_values("peso_total_ageb", ascending=False).reset_index(drop=True)
    perfil[RANKING_COL] = np.arange(1, len(perfil) + 1)

    geom = warehouse_gdf[[id_col, "geometry"]].drop_duplicates(subset=[id_col])
    ageb_gdf = geom.merge(perfil, on=id_col, how="inner")
    ageb_gdf = gpd.GeoDataFrame(ageb_gdf, geometry="geometry", crs=warehouse_gdf.crs)

    report.n_agebs_total = int(geom[id_col].nunique())
    report.n_agebs_con_perfil = int(ageb_gdf[id_col].nunique())
    report.n_agebs_sin_perfil = report.n_agebs_total - report.n_agebs_con_perfil
    return ageb_gdf, long_cluster, long_sector, report


__all__ = [
    "AggregationReport",
    "ageb_sector_weights",
    "ageb_cluster_weights",
    "build_ageb_universe",
]
