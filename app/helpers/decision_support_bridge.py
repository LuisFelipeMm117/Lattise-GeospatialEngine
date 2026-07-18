# app/helpers/decision_support_bridge.py
"""
Opportunity Explorer — puente hacia el Decision Support Engine.

Este módulo es el ÚNICO punto de la capa de aplicación que construye
el universo territorial (AGEB x comunidad x municipio). Reemplaza la
reimplementación paralela que vivía en `app/helpers/aggregation.py`
(`build_ageb_universe`, `ageb_cluster_weights`, `ageb_sector_weights`,
`build_community_summary`, `build_municipality_gdf`,
`build_municipality_summary`) — esa lógica ahora vive en un solo
lugar: `spatial.decision_support` (motor cerrado, probado en
`tests/test_decision_support.py`), y `app/helpers/aggregation.py`
quedó reducido a lo que nunca fue un duplicado (`ageb_direct_shock`).

Este archivo NO recalcula peso, comunidad dominante ni sector
dominante — eso lo hace exclusivamente
`spatial.decision_support.build_decision_support_report`. Lo único que
hace este módulo es:

  1. Invocar el motor (con caché de Streamlit — el motor mismo es
     agnóstico de `streamlit`, ver `spatial/decision_support/report.py`).
  2. "Aplanar" sus dataclasses (`AGEBProfile` / `MunicipalityProfile` /
     `CommunityProfile`) a los mismos DataFrames/GeoDataFrames que ya
     consumen `app/panels/*`, `app/components/map_view.py` y
     `app/components/search_sidebar.py` — mismos nombres de columna
     que antes (`cvegeo`, `peso_total_ageb`, `ranking_estatal`,
     `n_sectores_ageb`, `sector_peso`), para que ningún panel ni
     componente tenga que cambiar.
  3. Adjuntar la geometría: el reporte del motor es deliberadamente
     agnóstico de geopandas en su forma serializada (ver docstring de
     `DecisionSupportReport.to_parquet`), así que la geometría se toma
     directamente de `warehouse_gdf` (Stage 5, CERRADO) — nunca se
     recalcula ni se infiere geometría nueva.
  4. Derivar DOS agregados de presentación que el motor
     deliberadamente NO calcula por ser compuestos/específicos de UI,
     no perfiles base (ver `spatial/decision_support/report.py`,
     sección "Este módulo NUNCA responde"):
       - lista COMPLETA de municipios por comunidad (el motor solo
         expone el top-N vía `municipios_principales`)
       - comunidad dominante por municipio (`cluster_dominante`,
         usada para colorear el mapa a nivel municipal)
     Ambos se calculan con groupby/idxmax sobre columnas que el motor
     YA produjo (`cluster_id`, `peso_total_ageb` por AGEB) — nunca
     sobre `warehouse.parquet` crudo. Mismo principio que el resto de
     `app/`: presentación, no re-cómputo económico.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import pandas as pd
import streamlit as st

from spatial.decision_support.report import DecisionSupportReport, build_decision_support_report

from app.helpers.data_sources import AGEB_ID_COL
from app.helpers.formatting import color_for_index

# ── Renombres: campo del DecisionSupportReport -> columna legacy que ya
#    consumen los paneles / map_view / search_sidebar. Único lugar que
#    conoce este mapeo — si el motor cambia un nombre de campo, solo se
#    toca este diccionario, no cada panel. ──────────────────────────────────
_AGEB_RENAME = {
    "ageb": AGEB_ID_COL,
    "peso_total": "peso_total_ageb",
    "ranking": "ranking_estatal",
    "n_sectores": "n_sectores_ageb",
    "sector_dominante_peso": "sector_peso",
}
_COMMUNITY_RENAME = {"peso_total": "peso_economico"}
_MUNI_RENAME = {"peso_total": "peso"}


# ══════════════════════════════════════════════════════════
# Funciones puras (sin streamlit) — testeables directamente
# ══════════════════════════════════════════════════════════
def profiles_to_ageb_df(report: DecisionSupportReport) -> pd.DataFrame:
    """`AGEBProfile.to_dict()` por AGEB -> un DataFrame plano, columnas
    legacy. Sin geometría (se adjunta en `build_universe`/`attach_geometry`)."""
    if not report.ageb_profiles:
        return pd.DataFrame()
    df = pd.DataFrame(list(report.ageb_profiles.values()))
    return df.rename(columns=_AGEB_RENAME)


def profiles_to_community_df(report: DecisionSupportReport, ageb_df: pd.DataFrame) -> pd.DataFrame:
    """`CommunityProfile.to_dict()` por comunidad -> DataFrame legacy
    (reemplaza `build_community_summary`). `municipios` (lista COMPLETA,
    no solo principales) se deriva de `ageb_df` ya construido — el
    reporte solo expone el top-N (`municipios_principales`)."""
    if not report.community_profiles:
        return pd.DataFrame()
    df = pd.DataFrame(list(report.community_profiles.values())).rename(columns=_COMMUNITY_RENAME)

    if not ageb_df.empty and "cluster_id" in ageb_df.columns:
        municipios_full = (
            ageb_df.groupby("cluster_id")["municipio"]
            .apply(lambda s: sorted(s.dropna().unique().tolist()))
        )
        df["municipios"] = df["cluster_id"].map(municipios_full).apply(
            lambda v: v if isinstance(v, list) else []
        )
    else:
        df["municipios"] = [[] for _ in range(len(df))]

    df = df.sort_values("peso_economico", ascending=False).reset_index(drop=True)
    df["color"] = [color_for_index(i) for i in range(len(df))]
    return df


def dominant_cluster_by_municipio(ageb_df: pd.DataFrame) -> pd.DataFrame:
    """Comunidad dominante por municipio (argmax del `peso_total_ageb`
    agregado por (municipio, cluster_id)) — agregado de presentación
    que el motor no calcula (ver docstring del módulo). Opera
    exclusivamente sobre columnas YA producidas por el motor, nunca
    sobre pesos crudos del warehouse."""
    cols = ["municipio", "cluster_dominante", "peso_cluster_dominante"]
    if ageb_df.empty or "cluster_id" not in ageb_df.columns:
        return pd.DataFrame(columns=cols)
    grp = ageb_df.groupby(["municipio", "cluster_id"], as_index=False)["peso_total_ageb"].sum()
    if grp.empty:
        return pd.DataFrame(columns=cols)
    idx_dom = grp.groupby("municipio")["peso_total_ageb"].idxmax()
    dom = grp.loc[idx_dom].reset_index(drop=True).rename(
        columns={"cluster_id": "cluster_dominante", "peso_total_ageb": "peso_cluster_dominante"}
    )
    return dom[cols]


def profiles_to_muni_df(report: DecisionSupportReport, ageb_df: pd.DataFrame) -> pd.DataFrame:
    """`MunicipalityProfile.to_dict()` por municipio -> DataFrame legacy
    (reemplaza `build_municipality_summary`), con `cluster_dominante`
    derivado (ver `dominant_cluster_by_municipio`)."""
    if not report.municipality_profiles:
        return pd.DataFrame()
    df = pd.DataFrame(list(report.municipality_profiles.values())).rename(columns=_MUNI_RENAME)
    dom = dominant_cluster_by_municipio(ageb_df)
    df = df.merge(dom, on="municipio", how="left")

    if not ageb_df.empty and {"cluster_id", "cluster_nombre"}.issubset(ageb_df.columns):
        nombre_by_cluster = (
            ageb_df[["cluster_id", "cluster_nombre"]].drop_duplicates().set_index("cluster_id")["cluster_nombre"]
        )
        df["cluster_dominante_nombre"] = df["cluster_dominante"].map(nombre_by_cluster)
    else:
        df["cluster_dominante_nombre"] = None

    return df.sort_values("peso", ascending=False).reset_index(drop=True)


def attach_geometry(ageb_df: pd.DataFrame, warehouse_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Adjunta geometría desde `warehouse_gdf` (Stage 5, CERRADO) — el
    `DecisionSupportReport` es deliberadamente agnóstico de geopandas
    en su forma serializada (ver `to_parquet` en
    `spatial/decision_support/report.py`)."""
    geom = warehouse_gdf[[AGEB_ID_COL, "geometry"]].drop_duplicates(subset=[AGEB_ID_COL])
    merged = geom.merge(ageb_df, on=AGEB_ID_COL, how="inner")
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=warehouse_gdf.crs)


def build_municipality_gdf(ageb_gdf: gpd.GeoDataFrame, muni_df: pd.DataFrame) -> gpd.GeoDataFrame:
    """Disolución geométrica por municipio — mismo criterio que antes
    (`app.helpers.aggregation.build_municipality_gdf`), ahora sobre
    geometría/peso ya construidos por el motor."""
    dissolved = ageb_gdf.dissolve(by="municipio", aggfunc={"peso_total_ageb": "sum"}).reset_index()
    dissolved = dissolved.drop(columns=["peso_total_ageb"]).merge(
        muni_df, on="municipio", how="left",
    )
    return dissolved


# ══════════════════════════════════════════════════════════
# Orquestador cacheado — punto de entrada único desde la página
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner="Construyendo universo territorial…")
def build_universe(
    _warehouse_gdf: gpd.GeoDataFrame,
    artifact: dict,
    sector_names: dict,
    _spatial_matrix=None,
    _sim_gdf: Optional[gpd.GeoDataFrame] = None,
):
    """Reemplazo directo de `app.helpers.aggregation.build_ageb_universe`
    + `build_community_summary` + `build_municipality_gdf` +
    `build_municipality_summary`, pero sourcing TODO desde
    `spatial.decision_support.build_decision_support_report` — motor
    cerrado, probado, única fuente de verdad de peso/comunidad/sector
    dominante.

    Devuelve `(ageb_gdf, community_summary, muni_gdf, muni_summary,
    integrity_report, decision_report)` — mismas formas que ya
    consumían `app/panels/*`, `app/components/map_view.py` y
    `app/components/search_sidebar.py`; ningún panel necesita cambiar.

    Los argumentos con prefijo `_` no se usan como llave de caché de
    Streamlit (son GeoDataFrames/objetos no hasheables) — mismo
    criterio ya usado por `app.helpers.aggregation.build_ageb_universe`
    y `build_municipality_gdf` antes de este refactor.
    """
    warehouse_gdf = _warehouse_gdf
    decision_report = build_decision_support_report(
        warehouse_gdf, artifact, sector_names,
        spatial_matrix=_spatial_matrix, simulation_gdf=_sim_gdf,
    )

    ageb_df = profiles_to_ageb_df(decision_report)
    ageb_gdf = attach_geometry(ageb_df, warehouse_gdf)

    # Elección de presentación: el motor deja `impacto_propagado` en
    # `None` cuando un AGEB queda fuera de la simulación cargada — el
    # choropleth de la capa "Simulation Impact" necesita 0 numérico
    # explícito para esos AGEBs (mismo criterio que ya aplicaba la
    # página antes de este refactor, ver `IMPACTO_PROPAGADO_COL`).
    if "impacto_propagado" in ageb_gdf.columns:
        ageb_gdf["impacto_propagado"] = ageb_gdf["impacto_propagado"].fillna(0.0)

    community_summary = profiles_to_community_df(decision_report, ageb_gdf)
    muni_summary = profiles_to_muni_df(decision_report, ageb_gdf)
    muni_gdf = build_municipality_gdf(ageb_gdf, muni_summary)

    integrity_report = {
        **decision_report.aggregation_report,
        "n_agebs_asignados": decision_report.n_agebs,
        "n_agebs_sin_asignacion": decision_report.aggregation_report.get("n_agebs_sin_perfil", 0),
    }

    return ageb_gdf, community_summary, muni_gdf, muni_summary, integrity_report, decision_report


__all__ = [
    "build_universe",
    "profiles_to_ageb_df",
    "profiles_to_community_df",
    "profiles_to_muni_df",
    "dominant_cluster_by_municipio",
    "attach_geometry",
    "build_municipality_gdf",
]
