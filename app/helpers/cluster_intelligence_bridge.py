# app/helpers/cluster_intelligence_bridge.py
"""
Spatial Cluster Intelligence -- puente hacia spatial.decision_support.

Reemplaza la reimplementacion paralela que vivia en
`app/pages/4_Spatial_Cluster_Intelligence.py`
(`_ageb_cluster_weights`, `build_ageb_community_gdf`,
`build_community_summary`, `build_municipality_gdf`,
`build_municipality_summary`) -- la misma duplicacion que ya se cerro
para Opportunity Explorer (`app/helpers/decision_support_bridge.py`),
pero con un matiz nuevo encontrado en esta sesion: las dos paginas
calculaban "peso economico de una comunidad" con criterios DISTINTOS
y silenciosamente incompatibles.

    A) Pagina 4 (antes de esta correccion): solo la porcion de peso de
       cada AGEB que cae en su comunidad DOMINANTE -- pierde peso real
       de cualquier AGEB con sectores mixtos.
    B) decision_support (`peso_total`, ya usado por Opportunity
       Explorer): el peso TOTAL del AGEB atribuido entero a su
       comunidad dominante -- le regala a la dominante peso que en
       realidad pertenece a otra comunidad.

Decision de producto (explicita, con el usuario, ver conversacion):
usar la tercera definicion, `peso_granular`
(`spatial.decision_support.aggregation.community_granular_weights` /
`CommunityProfile.peso_granular`) -- reparte el peso de cada AGEB
exactamente donde corresponde, sin perder ni regalar nada. Se agrego
como campo NUEVO en `spatial/decision_support/`, sin tocar
`peso_total` (que sigue exactamente igual, cero regresion sobre lo ya
probado).

Este mismo principio se extiende, por consistencia, al peso total de
un MUNICIPIO: la version anterior de esta pagina sumaba
`ageb_gdf["peso"]` (peso SOLO en la comunidad dominante de cada AGEB)
por municipio -- el mismo defecto de perdida que tenia a nivel
comunidad. `MunicipalityProfile.peso_total` (ya existente, sin cambios
en esta sesion) nunca tuvo ese problema: siempre sumo el peso TOTAL de
cada AGEB sin pasar por ninguna comunidad dominante, asi que no hizo
falta agregarle un campo nuevo -- solo dejar de usar el sustituto con
perdida de la pagina y consumir el campo correcto que el motor ya
tenia.

Lo que la comunidad dominante de un AGEB determina siempre fue, y
sigue siendo, el color del AGEB en el mapa -- eso no cambia con nada
de lo anterior.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import pandas as pd
import streamlit as st

from spatial.decision_support.aggregation import ageb_sector_weights, build_ageb_universe
from spatial.decision_support.report import build_decision_support_report

try:
    from spatial.simulation.engine import (
        IMPACTO_DIRECTO_COL,
        IMPACTO_INDIRECTO_COL,
        IMPACTO_PROPAGADO_COL,
    )
except ImportError:  # pragma: no cover
    IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL = (
        "shock_directo", "impacto_indirecto", "impacto_propagado",
    )

from app.helpers.data_sources import AGEB_ID_COL
from app.helpers.formatting import color_for_index

_AGEB_RENAME = {"cluster_peso": "peso"}


# ══════════════════════════════════════════════════════════
# Funciones puras (sin streamlit) -- testeables directamente
# ══════════════════════════════════════════════════════════
def build_ageb_and_long(
    warehouse_gdf: gpd.GeoDataFrame, artifact: dict, sector_names: dict,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Reemplazo directo de `_ageb_cluster_weights` +
    `build_ageb_community_gdf` -- ahora sourcing 100% desde
    `spatial.decision_support.aggregation.build_ageb_universe` (motor
    cerrado, probado). Devuelve `(ageb_gdf, long_df, long_sector_df,
    integrity_report)` con los mismos nombres de columna que ya
    consumia la pagina (`peso`, no `cluster_peso`)."""
    ageb_gdf, long_cluster, long_sector, agg_report = build_ageb_universe(
        warehouse_gdf, artifact, sector_names
    )
    ageb_gdf = ageb_gdf.rename(columns=_AGEB_RENAME)

    integrity_report = agg_report.to_dict()
    integrity_report["n_agebs_asignados"] = integrity_report["n_agebs_con_perfil"]
    integrity_report["n_agebs_sin_asignacion"] = integrity_report["n_agebs_sin_perfil"]
    return ageb_gdf, long_cluster, long_sector, integrity_report


def build_community_summary(
    decision_report, ageb_gdf: pd.DataFrame,
) -> pd.DataFrame:
    """Reemplazo directo de `build_community_summary`, sourcing de
    `CommunityProfile` -- con una diferencia deliberada: `peso_economico`
    y `participacion_pct` vienen de `peso_granular` /
    `participacion_pct_granular` (ver docstring del modulo), NO de
    `peso_total`. `n_agebs`/`n_municipios` se quedan sin cambio (cuentan
    via comunidad dominante, igual que antes -- eso no formaba parte de
    la decision de producto sobre "peso economico")."""
    if not decision_report.community_profiles:
        return pd.DataFrame()
    df = pd.DataFrame(list(decision_report.community_profiles.values()))
    df["peso_economico"] = df["peso_granular"]
    df["participacion_pct"] = df["participacion_pct_granular"]

    if not ageb_gdf.empty and "cluster_id" in ageb_gdf.columns:
        municipios_full = (
            ageb_gdf.groupby("cluster_id")["municipio"]
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


def build_municipality_gdf_and_summary(
    ageb_gdf: gpd.GeoDataFrame,
    long_cluster: pd.DataFrame,
    decision_report,
    community_summary: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Reemplazo directo de `build_municipality_gdf` +
    `build_municipality_summary`.

    `cluster_dominante` por municipio: mismo criterio de siempre
    (argmax del peso agregado por (municipio, cluster_id)) -- pero
    ahora sobre `long_cluster` ya producido por el motor, no
    recalculado localmente.

    `peso` total del municipio: viene de `MunicipalityProfile.peso_total`
    (ya existente, sin cambios) en vez de disolver `ageb_gdf["peso"]`
    (que es solo la porcion dominante de cada AGEB, y por lo tanto
    pierde peso real -- mismo defecto que tenia el peso de comunidad,
    ver docstring del modulo)."""
    long_with_muni = long_cluster.merge(
        ageb_gdf[[AGEB_ID_COL, "municipio"]].drop_duplicates(), on=AGEB_ID_COL, how="inner"
    )
    muni_cluster = long_with_muni.groupby(["municipio", "cluster_id"], as_index=False)["peso"].sum()
    idx_dom = muni_cluster.groupby("municipio")["peso"].idxmax()
    muni_dominant = muni_cluster.loc[idx_dom].reset_index(drop=True).rename(
        columns={"cluster_id": "cluster_dominante", "peso": "peso_cluster_dominante"}
    )

    muni_df = pd.DataFrame(list(decision_report.municipality_profiles.values())).rename(
        columns={
            "peso_total": "peso",
            "impacto_directo_agregado": IMPACTO_DIRECTO_COL,
            "impacto_indirecto_agregado": IMPACTO_INDIRECTO_COL,
            "impacto_propagado_agregado": IMPACTO_PROPAGADO_COL,
        }
    )
    if decision_report.has_simulation:
        for c in (IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL):
            muni_df[c] = muni_df[c].fillna(0.0)
    muni_df = muni_df.merge(muni_dominant, on="municipio", how="left")

    color_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["color"]))
    nombre_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["nombre"]))
    muni_df["cluster_dominante_nombre"] = muni_df["cluster_dominante"].map(nombre_by_cluster)
    muni_df["color"] = muni_df["cluster_dominante"].map(color_by_cluster).fillna("#576073")
    muni_df = muni_df.sort_values("peso", ascending=False).reset_index(drop=True)

    dissolved = ageb_gdf.dissolve(by="municipio").reset_index()[["municipio", "geometry"]]
    muni_gdf = gpd.GeoDataFrame(
        dissolved.merge(muni_df, on="municipio", how="left"),
        geometry="geometry", crs=ageb_gdf.crs,
    )
    return muni_gdf, muni_df


def sector_diversity_by_ageb(warehouse_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Reemplazo directo de la agregacion inline que alimentaba
    `_compute_sector_diversity` -- ahora via
    `ageb_sector_weights` (motor cerrado, ya usado tambien para
    `sector_dominante`), agrupado a # de sectores distintos por AGEB."""
    long_sector = ageb_sector_weights(warehouse_gdf)
    return (
        long_sector.groupby(AGEB_ID_COL)["sector_serio"].nunique()
        .rename("n_sectores_ageb").reset_index()
    )


def aggregate_shock_by(sim_gdf: gpd.GeoDataFrame, id_map: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Agrega `simulation_gdf` (Stage 8C, ya calculado) por un grupo
    (cluster_id) usando un mapeo AGEB->grupo. Nunca recalcula shock ni
    propagacion -- solo groupby/sum sobre columnas existentes.

    Se mantiene como utilidad aparte (no se movio a
    `spatial.decision_support`) porque `CommunityProfile` no carga
    impacto de simulacion (a diferencia de `AGEBProfile` y
    `MunicipalityProfile`, que si lo hacen) -- ver
    `spatial/decision_support/profiles.py`. Es un merge+groupby trivial
    sobre un resultado ya cerrado, no una reimplementacion de peso o
    dominancia."""
    cols = [AGEB_ID_COL, IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]
    sim_df = pd.DataFrame(sim_gdf[cols])
    merged = id_map.merge(sim_df, on=AGEB_ID_COL, how="inner")
    return merged.groupby(group_col, as_index=False)[
        [IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]
    ].sum()


# ══════════════════════════════════════════════════════════
# Orquestador cacheado -- punto de entrada unico desde la pagina
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner="Construyendo universo territorial...")
def build_universe(
    _warehouse_gdf: gpd.GeoDataFrame,
    artifact: dict,
    sector_names: dict,
    _spatial_matrix=None,
    _sim_gdf: Optional[gpd.GeoDataFrame] = None,
):
    """Reemplazo directo de `build_ageb_community_gdf` +
    `build_community_summary` + `build_municipality_gdf` +
    `build_municipality_summary`, sourcing TODO desde
    `spatial.decision_support` -- motor cerrado, probado, unica fuente
    de verdad de peso/comunidad/sector dominante (incluyendo la
    definicion granular de peso de comunidad, ver docstring del
    modulo).

    Devuelve `(ageb_gdf, long_cluster, long_sector, community_summary,
    muni_gdf, muni_summary, integrity_report, decision_report)`.
    """
    warehouse_gdf = _warehouse_gdf
    ageb_gdf, long_cluster, long_sector, integrity_report = build_ageb_and_long(
        warehouse_gdf, artifact, sector_names
    )

    decision_report = build_decision_support_report(
        warehouse_gdf, artifact, sector_names,
        spatial_matrix=_spatial_matrix, simulation_gdf=_sim_gdf,
    )

    community_summary = build_community_summary(decision_report, ageb_gdf)
    muni_gdf, muni_summary = build_municipality_gdf_and_summary(
        ageb_gdf, long_cluster, decision_report, community_summary
    )

    return (
        ageb_gdf, long_cluster, long_sector, community_summary,
        muni_gdf, muni_summary, integrity_report, decision_report,
    )


__all__ = [
    "build_universe",
    "build_ageb_and_long",
    "build_community_summary",
    "build_municipality_gdf_and_summary",
    "sector_diversity_by_ageb",
    "aggregate_shock_by",
]
