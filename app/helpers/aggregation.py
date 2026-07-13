# app/helpers/aggregation.py
"""
Opportunity Explorer — agregaciones de presentación.

Ninguna función de este archivo reinvierte una matriz, vuelve a correr
Louvain, recalcula la propagación espacial o el shock. Todo es
groupby/argmax/merge de presentación sobre columnas que YA existen en:

    - `spatial.config.WAREHOUSE_PARQUET`     (Stage 5, CERRADO — una
      fila por (AGEB, sector_serio), columnas `n_establecimientos`,
      `empleo_total`).
    - `data/analytics/sector_cluster.json`   (Louvain, congelado offline).
    - `st.session_state["simulation_gdf"]`   (Stage 8C, OPCIONAL).

Mismo criterio de peso ya establecido en
`app/pages/4_Spatial_Cluster_Intelligence.py::_ageb_cluster_weights`:
peso = empleo_total si el AGEB tiene empleo registrado en algo, si no,
n_establecimientos (respaldo explícito, `peso_metodo` queda etiquetado
— nunca se descarta en silencio).
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import streamlit as st

from app.helpers.data_sources import (
    AGEB_ID_COL,
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
    SECTOR_COL,
)
from app.helpers.formatting import color_for_index, municipio_code


# ══════════════════════════════════════════════════════════
# Peso por (AGEB, sector) — respaldo empleo → establecimientos,
# calculado a nivel AGEB (no a nivel fila) para no mezclar métodos
# dentro del mismo AGEB.
# ══════════════════════════════════════════════════════════
def _weighted_long(warehouse_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    df = pd.DataFrame(warehouse_gdf.drop(columns="geometry"))
    df[SECTOR_COL] = df[SECTOR_COL].astype(str)

    emp_by_ageb = df.groupby(AGEB_ID_COL)["empleo_total"].sum()
    usa_empleo = emp_by_ageb[emp_by_ageb > 0].index
    df["peso"] = np.where(df[AGEB_ID_COL].isin(usa_empleo), df["empleo_total"], df["n_establecimientos"])
    df["peso_metodo"] = np.where(df[AGEB_ID_COL].isin(usa_empleo), "empleo", "establecimientos")
    return df


# ══════════════════════════════════════════════════════════
# AGEB × sector (peso) — para "sector dominante" y cobertura sectorial
# ══════════════════════════════════════════════════════════
def ageb_sector_weights(warehouse_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    df = _weighted_long(warehouse_gdf)
    long_sector = (
        df.groupby([AGEB_ID_COL, SECTOR_COL, "peso_metodo"], as_index=False)["peso"].sum()
    )
    return long_sector


# ══════════════════════════════════════════════════════════
# AGEB × comunidad (peso) — mismo criterio que Spatial Cluster
# Intelligence (`_ageb_cluster_weights`).
# ══════════════════════════════════════════════════════════
def ageb_cluster_weights(warehouse_gdf: gpd.GeoDataFrame, artifact: dict) -> tuple[pd.DataFrame, dict]:
    sector_to_cluster = artifact["sector_to_cluster"]
    df = _weighted_long(warehouse_gdf)

    mapeados_mask = df[SECTOR_COL].isin(sector_to_cluster.keys())
    n_no_mapeados = int((~mapeados_mask).sum())
    sectores_no_mapeados = sorted(df.loc[~mapeados_mask, SECTOR_COL].unique().tolist())
    df_mapeado = df.loc[mapeados_mask].copy()
    df_mapeado["cluster_id"] = df_mapeado[SECTOR_COL].map(sector_to_cluster).astype(int)

    long_cluster = (
        df_mapeado.groupby([AGEB_ID_COL, "cluster_id", "peso_metodo"], as_index=False)["peso"].sum()
    )

    report = {
        "n_registros_sector_no_mapeado": n_no_mapeados,
        "sectores_no_mapeados": sectores_no_mapeados,
        "n_sectores_en_warehouse": int(df[SECTOR_COL].nunique()),
    }
    return long_cluster, report


# ══════════════════════════════════════════════════════════
# UNIVERSO DE AGEB — perfil territorial: comunidad dominante, sector
# dominante, peso, municipio, cobertura sectorial, participación.
# Es el mismo "argmax(peso)" que Spatial Cluster Intelligence ya usa
# para la comunidad dominante, aplicado también a nivel sector.
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def build_ageb_universe(
    _warehouse_gdf: gpd.GeoDataFrame, artifact: dict, sector_names: dict
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Devuelve (ageb_gdf, long_cluster_df, long_sector_df, report).

    ageb_gdf — una fila por AGEB:
        cvegeo, geometry, municipio,
        cluster_id, cluster_peso, peso_metodo,
        sector_dominante, sector_dominante_nombre, sector_peso,
        peso_total_ageb, n_sectores_ageb, participacion_pct,
        ranking_estatal (1 = mayor peso_total_ageb del territorio).
    """
    warehouse_gdf = _warehouse_gdf
    long_cluster, report = ageb_cluster_weights(warehouse_gdf, artifact)
    long_sector = ageb_sector_weights(warehouse_gdf)

    # ── Comunidad dominante por AGEB (argmax peso) ─────────────────────
    idx_dom_cl = long_cluster.groupby(AGEB_ID_COL)["peso"].idxmax()
    dom_cluster = long_cluster.loc[idx_dom_cl].reset_index(drop=True).rename(
        columns={"cluster_id": "cluster_id", "peso": "cluster_peso"}
    )

    # ── Sector dominante por AGEB (argmax peso, granularidad sector) ──
    idx_dom_sec = long_sector.groupby(AGEB_ID_COL)["peso"].idxmax()
    dom_sector = long_sector.loc[idx_dom_sec].reset_index(drop=True).rename(
        columns={SECTOR_COL: "sector_dominante", "peso": "sector_peso"}
    )
    dom_sector["sector_dominante_nombre"] = dom_sector["sector_dominante"].map(
        lambda s: sector_names.get(str(s), f"Sector {s}")
    )

    # ── Peso total y cobertura sectorial (# sectores distintos con
    #    presencia en el AGEB, sin filtrar por mapeo a comunidad) ──────
    peso_total_ageb = long_sector.groupby(AGEB_ID_COL, as_index=False)["peso"].sum().rename(
        columns={"peso": "peso_total_ageb"}
    )
    n_sectores_ageb = long_sector.groupby(AGEB_ID_COL, as_index=False)[SECTOR_COL].nunique().rename(
        columns={SECTOR_COL: "n_sectores_ageb"}
    )

    perfil = (
        dom_cluster[[AGEB_ID_COL, "cluster_id", "cluster_peso", "peso_metodo"]]
        .merge(dom_sector[[AGEB_ID_COL, "sector_dominante", "sector_dominante_nombre", "sector_peso"]],
               on=AGEB_ID_COL, how="left")
        .merge(peso_total_ageb, on=AGEB_ID_COL, how="left")
        .merge(n_sectores_ageb, on=AGEB_ID_COL, how="left")
    )
    perfil["municipio"] = perfil[AGEB_ID_COL].map(municipio_code)

    peso_total_global = perfil["peso_total_ageb"].sum()
    perfil["participacion_pct"] = (
        perfil["peso_total_ageb"] / peso_total_global * 100 if peso_total_global else 0.0
    )
    perfil = perfil.sort_values("peso_total_ageb", ascending=False).reset_index(drop=True)
    perfil["ranking_estatal"] = np.arange(1, len(perfil) + 1)

    geom = warehouse_gdf[[AGEB_ID_COL, "geometry"]].drop_duplicates(subset=[AGEB_ID_COL])
    ageb_gdf = geom.merge(perfil, on=AGEB_ID_COL, how="inner")
    ageb_gdf = gpd.GeoDataFrame(ageb_gdf, geometry="geometry", crs=warehouse_gdf.crs)

    report["n_agebs_asignados"] = int(ageb_gdf[AGEB_ID_COL].nunique())
    report["n_agebs_sin_asignacion"] = int(geom[AGEB_ID_COL].nunique() - ageb_gdf[AGEB_ID_COL].nunique())
    report["n_sectores_total_catalogo"] = len(sector_names) if sector_names else None
    return ageb_gdf, long_cluster, long_sector, report


# ══════════════════════════════════════════════════════════
# RESUMEN POR COMUNIDAD — mismo cálculo que Spatial Cluster
# Intelligence (`build_community_summary`), sobre el `ageb_gdf` de este
# módulo.
# ══════════════════════════════════════════════════════════
def build_community_summary(ageb_gdf: gpd.GeoDataFrame, artifact: dict) -> pd.DataFrame:
    clusters_meta = artifact["clusters"]
    peso_total_global = ageb_gdf["peso_total_ageb"].sum()

    filas = []
    for cl_key, cl in clusters_meta.items():
        sub = ageb_gdf[ageb_gdf["cluster_id"] == int(cl_key)]
        peso_econ = float(sub["peso_total_ageb"].sum())
        filas.append({
            "cluster_id": int(cl_key),
            "nombre": cl["nombre"],
            "sectores": cl["sectores"],
            "n_sectores": cl["n_sectores"],
            "centralidad_media": cl["centralidad_media"],
            "bl_media": cl["bl_media"],
            "fl_media": cl["fl_media"],
            "n_agebs": int(sub[AGEB_ID_COL].nunique()),
            "municipios": sorted(sub["municipio"].unique().tolist()),
            "n_municipios": int(sub["municipio"].nunique()),
            "peso_economico": peso_econ,
            "participacion_pct": (peso_econ / peso_total_global * 100) if peso_total_global else 0.0,
        })
    df = pd.DataFrame(filas).sort_values("peso_economico", ascending=False).reset_index(drop=True)
    df["color"] = [color_for_index(i) for i in range(len(df))]
    return df


# ══════════════════════════════════════════════════════════
# DISOLUCIÓN MUNICIPAL — misma agregación geométrica que Spatial
# Cluster Intelligence (`build_municipality_gdf` / `_summary`).
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def build_municipality_gdf(
    _ageb_gdf: gpd.GeoDataFrame, _long_cluster_df: pd.DataFrame
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    ageb_gdf = _ageb_gdf
    long_df = _long_cluster_df.merge(
        ageb_gdf[[AGEB_ID_COL, "municipio"]].drop_duplicates(), on=AGEB_ID_COL, how="inner"
    )
    muni_cluster = long_df.groupby(["municipio", "cluster_id"], as_index=False)["peso"].sum()
    idx_dom = muni_cluster.groupby("municipio")["peso"].idxmax()
    muni_dominant = muni_cluster.loc[idx_dom].reset_index(drop=True).rename(
        columns={"cluster_id": "cluster_dominante", "peso": "peso_cluster_dominante"}
    )

    dissolved = ageb_gdf.dissolve(by="municipio", aggfunc={"peso_total_ageb": "sum"}).reset_index()
    dissolved = dissolved.rename(columns={"peso_total_ageb": "peso"})
    n_agebs = ageb_gdf.groupby("municipio")[AGEB_ID_COL].nunique().rename("n_agebs")
    dissolved = dissolved.merge(n_agebs, on="municipio", how="left")
    dissolved = dissolved.merge(muni_dominant, on="municipio", how="left")

    peso_total = dissolved["peso"].sum()
    dissolved["participacion_pct"] = (dissolved["peso"] / peso_total * 100) if peso_total else 0.0
    return dissolved, muni_cluster


def build_municipality_summary(
    muni_gdf: gpd.GeoDataFrame, community_summary: pd.DataFrame, muni_shock: Optional[pd.DataFrame]
) -> pd.DataFrame:
    color_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["color"]))
    nombre_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["nombre"]))

    df = pd.DataFrame(muni_gdf.drop(columns="geometry")).copy()
    df["cluster_dominante_nombre"] = df["cluster_dominante"].map(nombre_by_cluster)
    df["color"] = df["cluster_dominante"].map(color_by_cluster).fillna("#576073")

    if muni_shock is not None and not muni_shock.empty:
        df = df.merge(muni_shock, on="municipio", how="left")
        for c in (IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL):
            df[c] = df[c].fillna(0.0)
    return df.sort_values("peso", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════
# AGREGACIÓN DE SHOCK — nunca recalcula shock ni propagación, solo
# groupby/sum sobre `simulation_gdf` ya producido por Run Simulation.
# ══════════════════════════════════════════════════════════
def aggregate_shock_by(sim_gdf: gpd.GeoDataFrame, id_map: pd.DataFrame, group_col: str) -> tuple[pd.DataFrame, dict]:
    cols = [AGEB_ID_COL, IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]
    sim_df = pd.DataFrame(sim_gdf[cols])
    merged = id_map.merge(sim_df, on=AGEB_ID_COL, how="inner")

    coverage = {
        "n_agebs_simulados": int(sim_df[AGEB_ID_COL].nunique()),
        "n_agebs_con_grupo_y_shock": int(merged[AGEB_ID_COL].nunique()),
        "n_agebs_shock_sin_grupo": int(sim_df[AGEB_ID_COL].nunique() - merged[AGEB_ID_COL].nunique()),
    }
    grouped = merged.groupby(group_col, as_index=False)[
        [IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]
    ].sum()
    return grouped, coverage


def ageb_direct_shock(sim_gdf: Optional[gpd.GeoDataFrame], cvegeo: str) -> Optional[dict]:
    """Lectura directa (sin agregación) del impacto ya calculado para un
    AGEB puntual en `simulation_gdf`."""
    if sim_gdf is None:
        return None
    row = sim_gdf[sim_gdf[AGEB_ID_COL] == cvegeo]
    if row.empty:
        return None
    row = row.iloc[0]
    return {
        IMPACTO_DIRECTO_COL: float(row[IMPACTO_DIRECTO_COL]),
        IMPACTO_INDIRECTO_COL: float(row[IMPACTO_INDIRECTO_COL]),
        IMPACTO_PROPAGADO_COL: float(row[IMPACTO_PROPAGADO_COL]),
    }
