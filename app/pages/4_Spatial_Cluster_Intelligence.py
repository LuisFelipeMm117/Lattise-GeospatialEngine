# app/pages/3_Spatial_Cluster_Intelligence.py
"""
Lattise Studio — Spatial Cluster Intelligence
Representación territorial de comunidades económicas — 6 Layers sobre el
mismo mapa y la misma interfaz.

Layers:
    1. Economic Communities — comunidad Louvain dominante por AGEB.
    2. Propagation Layer    — Propagated Impact / Spatial Spillover /
                               Shock Intensity / Decay Effect (requiere
                               una simulación cargada en Run Simulation).
    3. Impact Layer         — Direct / Indirect / Total Impact por AGEB
                               (sin referencia a comunidades).
    4. Municipality Layer   — geometría disuelta a nivel municipal:
                               cluster dominante, # AGEB, peso, impacto.
    5. Infrastructure Layer — arquitectura preparada (roads, railways,
                               industrial parks, airports, logistic
                               centers, universities); sin datos reales
                               todavía, listo para GeoJSON.
    6. Opportunity Layer    — índice compuesto (Opportunity Score) sobre
                               variables 100% existentes, sin IA/ML.

PRINCIPIO DE ESTE ARCHIVO: cada Layer es un renderer independiente
(clases *Layer) que implementa la misma interfaz —
    variable_options() · build_map_traces() · detail_panel() ·
    ranking() · insights()
— y todas comparten el mismo mapa (una sola figura Plotly), el mismo
panel derecho, el mismo bloque de ranking/insights y el mismo filtro de
comunidades activas de la izquierda. Cambiar de Layer NUNCA reconstruye
la página: solo cambia qué renderer se despacha.

FUENTES DE DATOS — solo lectura de artefactos ya congelados:
    1. data/analytics/sector_cluster.json  (Louvain, generado offline por
       scripts/build_sector_clusters.py — nunca se recalcula aquí).
    2. spatial.config.WAREHOUSE_PARQUET    (Stage 5, CERRADO).
    3. st.session_state["simulation_gdf"/"simulation_report"] (Stage 8C,
       producidos por Run Simulation — OPCIONAL, nunca recalculados).

Todas las magnitudes nuevas que aparecen en este archivo (peso por AGEB,
disolución municipal, Opportunity Score, Decay Effect, etc.) son
agregaciones/aritmética de presentación sobre columnas que YA existen en
(1)-(3) — nunca se reinvierte una matriz, nunca se vuelve a correr
Louvain, nunca se recalcula la propagación espacial ni el shock.
"""
from __future__ import annotations

import json
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Resolución de rutas del repo (app/pages/ → app/ → repo root) ───────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spatial.config import AGEB_ID_COL, DATA_DIR, WAREHOUSE_PARQUET  # noqa: E402
from spatial.warehouse.builder import SECTOR_COL  # noqa: E402 — solo el nombre de columna

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

SECTOR_CLUSTER_JSON = DATA_DIR / "analytics" / "sector_cluster.json"
INFRASTRUCTURE_DIR = DATA_DIR / "analytics" / "infrastructure"
# Arquitectura preparada para futuras capas de infraestructura — cada
# entrada se activa sola en cuanto exista el GeoJSON correspondiente en
# disco. Ningún dato real se inventa aquí.
INFRASTRUCTURE_SOURCES = {
    "roads":            {"label": "Roads",             "icon": "🛣️", "file": "roads.geojson"},
    "railways":         {"label": "Railways",           "icon": "🚆", "file": "railways.geojson"},
    "industrial_parks": {"label": "Industrial Parks",   "icon": "🏭", "file": "industrial_parks.geojson"},
    "airports":         {"label": "Airports",           "icon": "✈️", "file": "airports.geojson"},
    "logistic_centers": {"label": "Logistic Centers",   "icon": "📦", "file": "logistic_centers.geojson"},
    "universities":     {"label": "Universities",       "icon": "🎓", "file": "universities.geojson"},
}

st.set_page_config(
    page_title="Spatial Cluster Intelligence — Lattise Studio",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

:root {
    --bg:        #0B0F17;
    --panel:     #10151F;
    --panel-hi:  #171F2C;
    --border:    #212B3B;
    --text:      #F4F5F7;
    --muted:     #8A93A6;
    --muted-dim: #576073;
    --accent:    #5B8DEF;
    --ok:        #34D399;
    --warn:      #F5B942;
    --bad:       #F87171;
}
html, body, .stApp { background: var(--bg) !important; }
* { font-family: 'Inter', sans-serif; }
header {visibility: hidden;}
[data-testid="stToolbar"]     {display: none;}
[data-testid="stDecoration"]  {display: none;}
[data-testid="stStatusWidget"]{display: none;}
footer {visibility: hidden;}
#MainMenu {visibility: hidden;}
.block-container { max-width: 1540px; padding-top: 1.2rem; padding-bottom: 2.5rem; }

.kicker {
    font-family: 'Space Mono', monospace; font-size: 11px; letter-spacing: 3px;
    text-transform: uppercase; color: var(--accent);
}
.page-title { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.8px; color: var(--text); margin: 2px 0 10px 0; }
.subtitle { color: var(--muted); font-size: 13.5px; margin-bottom: 14px; }

.layer-badge {
    display: inline-block; font-family: 'Space Mono', monospace; font-size: 10px;
    letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent);
    border: 1px solid var(--border); background: var(--panel); border-radius: 999px;
    padding: 4px 12px; margin-bottom: 10px;
}

.community-card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 12px; margin-bottom: 7px;
}
.community-card.active { border-color: var(--accent); background: var(--panel-hi); }
.community-card.dim { opacity: 0.4; }
.cc-head { display: flex; align-items: center; gap: 8px; }
.cc-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.cc-name { font-size: 12.5px; font-weight: 600; color: var(--text); line-height: 1.25; }
.cc-meta { font-family: 'Space Mono', monospace; font-size: 10.5px; color: var(--muted); margin-top: 4px; padding-left: 18px; }

.detail-panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 18px 20px; position: sticky; top: 12px;
}
.detail-empty {
    background: var(--panel); border: 1px dashed var(--border); border-radius: 14px;
    padding: 30px 20px; text-align: center; color: var(--muted); font-size: 13px;
}
.detail-title { font-size: 1.05rem; font-weight: 800; color: var(--text); margin: 2px 0 2px 0; }
.detail-sub { font-family: 'Space Mono', monospace; font-size: 10px; letter-spacing: 1.5px;
              text-transform: uppercase; color: var(--muted); margin-bottom: 12px; }
.detail-kpi-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
.detail-kpi { background: var(--panel-hi); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.detail-kpi-label { font-family: 'Space Mono', monospace; font-size: 9px; letter-spacing: 1px;
                     text-transform: uppercase; color: var(--muted); }
.detail-kpi-value { font-size: 1.05rem; font-weight: 700; color: var(--text); margin-top: 2px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
.tag { background: var(--panel-hi); border: 1px solid var(--border); border-radius: 999px;
       padding: 3px 10px; font-size: 11px; color: var(--muted); }
.tag.level-high   { color: var(--ok); border-color: var(--ok); }
.tag.level-medium { color: var(--warn); border-color: var(--warn); }
.tag.level-low    { color: var(--muted); }
.section-label { font-family: 'Space Mono', monospace; font-size: 10px; letter-spacing: 2px;
                  text-transform: uppercase; color: var(--muted); margin: 14px 0 6px 0; }

.legend-card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 14px; margin: 8px 0 14px 0; font-size: 12px; color: var(--muted);
}
.legend-title { font-family: 'Space Mono', monospace; font-size: 10px; letter-spacing: 1.5px;
                 text-transform: uppercase; color: var(--text); margin-bottom: 6px; }
.legend-grad { height: 8px; border-radius: 4px; margin: 4px 0; }
.legend-scale-row { display: flex; justify-content: space-between; font-family: 'Space Mono', monospace; font-size: 10px; }
.legend-chip-row { display: flex; flex-wrap: wrap; gap: 8px; }
.legend-chip { display: flex; align-items: center; gap: 5px; font-size: 11px; }
.legend-chip .dot { width: 9px; height: 9px; border-radius: 50%; }

.insight-card {
    background: var(--panel); border-left: 3px solid var(--accent); border-radius: 0 10px 10px 0;
    padding: 10px 14px; margin-bottom: 8px; font-size: 13px; color: var(--text);
}
.insight-card.shock { border-left-color: var(--warn); }
.insight-card.opportunity { border-left-color: var(--ok); }

.empty-state {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 40px; text-align: center; color: var(--muted);
}
.empty-state code { color: var(--accent); }
.soon-card {
    background: var(--panel); border: 1px dashed var(--border); border-radius: 10px;
    padding: 12px 14px; margin-bottom: 8px; display: flex; align-items: center; gap: 10px;
    color: var(--muted); font-size: 13px;
}
.soon-card .icon { font-size: 18px; }
.soon-card .ready { color: var(--ok); font-family: 'Space Mono', monospace; font-size: 10px; margin-left: auto; }
.soon-card .pending { color: var(--muted-dim); font-family: 'Space Mono', monospace; font-size: 10px; margin-left: auto; }
hr.thin { border: none; border-top: 1px solid var(--border); margin: 6px 0 16px 0; }
</style>
""", unsafe_allow_html=True)


def _md(html: str) -> None:
    st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)


def _municipio_code(cvegeo: str) -> str:
    cvegeo = str(cvegeo)
    return cvegeo[2:5] if len(cvegeo) >= 5 else "—"


def _format_compact(v: float) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000:
        return f"{sign}{v/1_000_000:,.2f}M"
    if v >= 1_000:
        return f"{sign}{v/1_000:,.1f}K"
    return f"{sign}{v:,.0f}"


def _short_name(nombre: str) -> str:
    return nombre.split("—", 1)[-1].strip()


def _minmax_norm(s: pd.Series) -> pd.Series:
    """Normalización min-max 0..1. Serie constante → 0.5 en todos (evita
    división por cero sin inventar dispersión donde no la hay)."""
    lo, hi = s.min(), s.max()
    if hi - lo < 1e-12:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


_PALETTE = [
    "#5B8DEF", "#34D399", "#F5B942", "#F87171", "#A78BFA", "#22D3EE",
    "#FB923C", "#4ADE80", "#F472B6", "#818CF8", "#FACC15", "#2DD4BF",
    "#FCA5A5", "#93C5FD", "#C4B5FD", "#6EE7B7", "#FDBA74", "#E879F9",
    "#67E8F9", "#BEF264",
]
_LEVEL_COLOR = {"High": "#34D399", "Medium": "#F5B942", "Low": "#576073"}


# ══════════════════════════════════════════════════════════
# CARGA — artefactos congelados, solo lectura
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def load_cluster_artifact() -> Optional[dict]:
    if not SECTOR_CLUSTER_JSON.exists():
        return None
    with open(SECTOR_CLUSTER_JSON, encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource(show_spinner="Loading spatial warehouse…")
def load_warehouse_gdf() -> Optional[gpd.GeoDataFrame]:
    if not Path(WAREHOUSE_PARQUET).exists():
        return None
    return gpd.read_parquet(WAREHOUSE_PARQUET)


# ══════════════════════════════════════════════════════════
# AGREGACIÓN DE PRESENTACIÓN — AGEB × comunidad
# ══════════════════════════════════════════════════════════
def _ageb_cluster_weights(warehouse_gdf: gpd.GeoDataFrame, artifact: dict) -> tuple[pd.DataFrame, dict]:
    """(AGEB, sector) del warehouse + sector_to_cluster del artefacto →
    (AGEB, cluster_id, peso) en formato largo. peso = empleo_total si el
    AGEB tiene empleo registrado en algo, si no, n_establecimientos
    (mismo criterio de respaldo explícito que usa WarehouseBuilder para
    ω_{g,s}). Sectores sin mapeo en el artefacto se excluyen y reportan,
    nunca se ocultan."""
    sector_to_cluster = artifact["sector_to_cluster"]
    df = pd.DataFrame(warehouse_gdf.drop(columns="geometry"))
    df[SECTOR_COL] = df[SECTOR_COL].astype(str)

    mapeados_mask = df[SECTOR_COL].isin(sector_to_cluster.keys())
    n_no_mapeados = int((~mapeados_mask).sum())
    sectores_no_mapeados = sorted(df.loc[~mapeados_mask, SECTOR_COL].unique().tolist())
    df = df.loc[mapeados_mask].copy()
    df["cluster_id"] = df[SECTOR_COL].map(sector_to_cluster).astype(int)

    emp_by_ageb = df.groupby(AGEB_ID_COL)["empleo_total"].sum()
    usa_empleo = emp_by_ageb[emp_by_ageb > 0].index
    df["peso"] = np.where(df[AGEB_ID_COL].isin(usa_empleo), df["empleo_total"], df["n_establecimientos"])
    df["peso_metodo"] = np.where(df[AGEB_ID_COL].isin(usa_empleo), "empleo", "establecimientos")

    long_df = (
        df.groupby([AGEB_ID_COL, "cluster_id", "peso_metodo"], as_index=False)["peso"].sum()
    )
    n_sectores_en_warehouse = int(df[SECTOR_COL].nunique())

    report = {
        "n_registros_sector_no_mapeado": n_no_mapeados,
        "sectores_no_mapeados": sectores_no_mapeados,
        "n_sectores_en_warehouse": n_sectores_en_warehouse,
    }
    return long_df, report


def build_ageb_community_gdf(
    warehouse_gdf: gpd.GeoDataFrame, artifact: dict
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, dict]:
    """Devuelve (ageb_gdf con comunidad dominante, tabla larga AGEB×cluster
    con todos los pesos —usada por Municipality y Opportunity—, reporte
    de integridad)."""
    long_df, report = _ageb_cluster_weights(warehouse_gdf, artifact)

    idx_dominante = long_df.groupby(AGEB_ID_COL)["peso"].idxmax()
    dominante = long_df.loc[idx_dominante].reset_index(drop=True)
    peso_total_ageb = long_df.groupby(AGEB_ID_COL, as_index=False)["peso"].sum().rename(
        columns={"peso": "peso_total_ageb"}
    )
    dominante = dominante.merge(peso_total_ageb, on=AGEB_ID_COL, how="left")
    dominante["municipio"] = dominante[AGEB_ID_COL].map(_municipio_code)

    geom = warehouse_gdf[[AGEB_ID_COL, "geometry"]].drop_duplicates(subset=[AGEB_ID_COL])
    gdf_out = geom.merge(dominante, on=AGEB_ID_COL, how="inner")
    gdf_out = gpd.GeoDataFrame(gdf_out, geometry="geometry", crs=warehouse_gdf.crs)

    report["n_agebs_asignados"] = int(gdf_out[AGEB_ID_COL].nunique())
    report["n_agebs_sin_asignacion"] = int(geom[AGEB_ID_COL].nunique() - gdf_out[AGEB_ID_COL].nunique())
    return gdf_out, long_df, report


def build_community_summary(ageb_gdf: gpd.GeoDataFrame, artifact: dict) -> pd.DataFrame:
    clusters_meta = artifact["clusters"]
    peso_total_global = ageb_gdf["peso"].sum()

    filas = []
    for cl_key, cl in clusters_meta.items():
        sub = ageb_gdf[ageb_gdf["cluster_id"] == int(cl_key)]
        peso_econ = float(sub["peso"].sum())
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
    df["color"] = [_PALETTE[i % len(_PALETTE)] for i in range(len(df))]
    return df


def get_simulation_gdf() -> Optional[gpd.GeoDataFrame]:
    if "simulation_gdf" not in st.session_state or "simulation_report" not in st.session_state:
        return None
    sim_gdf = st.session_state["simulation_gdf"]
    cols = [AGEB_ID_COL, IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]
    if any(c not in sim_gdf.columns for c in cols):
        return None
    return sim_gdf


def aggregate_shock_by(sim_gdf: gpd.GeoDataFrame, id_map: pd.DataFrame, group_col: str) -> tuple[pd.DataFrame, dict]:
    """Une simulation_gdf (Stage 8C, ya calculado) con un mapeo AGEB→grupo
    (cluster_id o municipio) y agrega sum() por grupo. Nunca recalcula
    shock ni propagación — solo groupby/sum sobre columnas existentes."""
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


# ══════════════════════════════════════════════════════════
# AGREGACIÓN — Municipality Layer (disolución geométrica)
# ══════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def build_municipality_gdf(_ageb_gdf: gpd.GeoDataFrame, _long_df: pd.DataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Disuelve geometría AGEB→municipio (agregación geométrica pura, no
    económica) y calcula el cluster dominante por municipio con el mismo
    criterio de argmax(peso) ya usado a nivel AGEB."""
    ageb_gdf = _ageb_gdf
    long_df = _long_df.merge(
        ageb_gdf[[AGEB_ID_COL, "municipio"]].drop_duplicates(), on=AGEB_ID_COL, how="inner"
    )
    muni_cluster = long_df.groupby(["municipio", "cluster_id"], as_index=False)["peso"].sum()
    idx_dom = muni_cluster.groupby("municipio")["peso"].idxmax()
    muni_dominant = muni_cluster.loc[idx_dom].reset_index(drop=True).rename(
        columns={"cluster_id": "cluster_dominante", "peso": "peso_cluster_dominante"}
    )

    dissolved = ageb_gdf.dissolve(by="municipio", aggfunc={"peso": "sum"}).reset_index()
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
# OPPORTUNITY SCORE — índice compuesto, sin IA/ML, variables existentes
# ══════════════════════════════════════════════════════════
DEFAULT_OPPORTUNITY_WEIGHTS = {
    "impacto_economico": 0.30,   # peso económico del AGEB (o |impacto propagado| si hay shock)
    "participacion":     0.15,   # participación del AGEB en el peso económico total
    "centralidad":       0.20,   # centralidad_media de la comunidad dominante del AGEB
    "diversidad":        0.15,   # 1 - HHI de la mezcla de comunidades presentes en el AGEB
    "especializacion":   0.10,   # concentración en la comunidad dominante (complemento de diversidad)
    "cobertura":         0.10,   # # sectores presentes en el AGEB / # sectores totales del warehouse
}


def build_opportunity_scores(
    ageb_gdf: gpd.GeoDataFrame,
    long_df: pd.DataFrame,
    community_summary: pd.DataFrame,
    n_sectores_warehouse: int,
    sim_gdf: Optional[gpd.GeoDataFrame],
    weights: dict,
) -> pd.DataFrame:
    """Índice compuesto 100% aritmético sobre variables ya calculadas
    aguas arriba (peso por AGEB, centralidad Louvain, mezcla de
    comunidades por AGEB, cobertura sectorial, impacto de simulación si
    existe). No es un modelo — es una normalización + suma ponderada."""
    df = pd.DataFrame(ageb_gdf.drop(columns="geometry")).copy()

    peso_total = df["peso_total_ageb"].sum()
    df["participacion"] = df["peso_total_ageb"] / peso_total if peso_total else 0.0

    centralidad_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["centralidad_media"]))
    df["centralidad"] = df["cluster_id"].map(centralidad_by_cluster).fillna(0.0)

    # diversidad/especialización: mezcla de comunidades dentro de cada AGEB
    mix = long_df.merge(df[[AGEB_ID_COL, "peso_total_ageb"]], on=AGEB_ID_COL, how="inner")
    mix["share"] = np.where(mix["peso_total_ageb"] > 0, mix["peso"] / mix["peso_total_ageb"], 0.0)
    hhi = mix.groupby(AGEB_ID_COL)["share"].apply(lambda s: float((s ** 2).sum()))
    df = df.merge(hhi.rename("hhi"), on=AGEB_ID_COL, how="left")
    df["diversidad"] = 1.0 - df["hhi"].fillna(1.0)
    df["especializacion"] = df["hhi"].fillna(1.0)

    # cobertura: # sectores distintos con establecimientos en el AGEB / total de sectores del warehouse
    # (calculado antes de colapsar a nivel cluster — ver _compute_sector_diversity)
    _sector_counts = _sector_diversity_cache.get("df")
    if _sector_counts is None:
        df["cobertura"] = 0.0
    else:
        cov = _sector_counts.set_index(AGEB_ID_COL)["n_sectores_ageb"]
        df["cobertura"] = df[AGEB_ID_COL].map(cov).fillna(0.0) / max(n_sectores_warehouse, 1)

    if sim_gdf is not None:
        sim_df = pd.DataFrame(sim_gdf[[AGEB_ID_COL, IMPACTO_PROPAGADO_COL]])
        sim_df["_impacto_abs"] = sim_df[IMPACTO_PROPAGADO_COL].abs()
        df = df.merge(sim_df[[AGEB_ID_COL, "_impacto_abs"]], on=AGEB_ID_COL, how="left")
        df["impacto_economico"] = df["_impacto_abs"].fillna(0.0)
        df["impacto_fuente"] = "impacto_propagado (simulación)"
    else:
        df["impacto_economico"] = df["peso_total_ageb"]
        df["impacto_fuente"] = "peso_economico (sin simulación)"

    componentes = list(weights.keys())
    for c in componentes:
        df[f"{c}_norm"] = _minmax_norm(df[c])

    total_w = sum(weights.values()) or 1.0
    df["opportunity_score"] = sum(df[f"{c}_norm"] * (weights[c] / total_w) for c in componentes)

    df["nivel"] = np.select(
        [df["opportunity_score"] >= 0.66, df["opportunity_score"] >= 0.33],
        ["High", "Medium"], default="Low",
    )
    df["municipio"] = df[AGEB_ID_COL].map(_municipio_code)
    return df


# Cache auxiliar simple para evitar recomputar cobertura sectorial dos veces
# por rerun (no es un artefacto persistido, solo memoria de proceso).
_sector_diversity_cache: dict = {}


def _compute_sector_diversity(long_source_df: pd.DataFrame) -> None:
    """Calcula # sectores distintos con presencia por AGEB, directamente
    desde el warehouse (antes de colapsar a cluster), y lo deja en caché
    de proceso para build_opportunity_scores."""
    _sector_diversity_cache["df"] = long_source_df


# ══════════════════════════════════════════════════════════
# INSIGHTS — reglas determinísticas, sin IA
# ══════════════════════════════════════════════════════════
def generate_structural_insights(summary: pd.DataFrame) -> list[str]:
    out = []
    if summary.empty:
        return out
    top = summary.iloc[0]
    out.append(
        f"La <b>{_short_name(top['nombre'])}</b> concentra el <b>{top['participacion_pct']:.0f}%</b> "
        f"de la actividad económica territorial ({top['n_agebs']} AGEB, {top['n_sectores']} sectores)."
    )
    cum = summary["participacion_pct"].cumsum()
    n_top = min(int((cum < 80).sum()) + 1, len(summary))
    out.append(
        f"Las <b>{n_top}</b> comunidades principales representan el <b>{cum.iloc[n_top-1]:.0f}%</b> "
        f"de la actividad registrada."
    )
    conectiva = summary.sort_values("n_municipios", ascending=False).iloc[0]
    out.append(
        f"La <b>{_short_name(conectiva['nombre'])}</b> presenta la mayor conectividad territorial, "
        f"con presencia en <b>{conectiva['n_municipios']}</b> municipios."
    )
    return out


def generate_shock_insights_by_group(df_with_shock: pd.DataFrame, name_col: str) -> list[str]:
    out = []
    if df_with_shock.empty:
        return out
    s = df_with_shock.copy()
    s["abs_propagado"] = s[IMPACTO_PROPAGADO_COL].abs()
    total_prop = s["abs_propagado"].sum()
    if total_prop <= 0:
        return out

    lider = s.sort_values("abs_propagado", ascending=False).iloc[0]
    out.append(
        f"<b>{lider[name_col]}</b> absorbió el mayor impacto del choque simulado: "
        f"<b>{lider['abs_propagado']/total_prop*100:.0f}%</b> del impacto propagado total."
    )
    s_sorted = s.sort_values("abs_propagado", ascending=False)
    cum = s_sorted["abs_propagado"].cumsum() / total_prop * 100
    n_conc = min(int((cum < 80).sum()) + 1, len(s_sorted))
    out.append(
        f"La propagación económica permanece concentrada dentro de <b>{n_conc}</b> unidad(es), "
        f"que reciben el <b>{cum.iloc[n_conc-1]:.0f}%</b> del impacto propagado total."
    )
    receptoras = s[s["abs_propagado"] > 1e-9].copy()
    if not receptoras.empty:
        receptoras["fuga_indirecta_pct"] = receptoras[IMPACTO_INDIRECTO_COL].abs() / receptoras["abs_propagado"] * 100
        resiliente = receptoras.sort_values("fuga_indirecta_pct", ascending=True).iloc[0]
        out.append(
            f"<b>{resiliente[name_col]}</b> mostró mayor resiliencia: solo "
            f"<b>{resiliente['fuga_indirecta_pct']:.0f}%</b> de su impacto se propagó como efecto indirecto."
        )
    return out


def generate_municipality_insights(muni_summary: pd.DataFrame) -> list[str]:
    out = []
    if muni_summary.empty:
        return out
    top = muni_summary.iloc[0]
    out.append(
        f"El municipio <b>{top['municipio']}</b> concentra el <b>{top['participacion_pct']:.0f}%</b> "
        f"del peso económico territorial, con <b>{int(top['n_agebs'])}</b> AGEB y especialización dominante en "
        f"<b>{_short_name(top['cluster_dominante_nombre'])}</b>."
    )
    n_munis_top80 = min(int((muni_summary["participacion_pct"].cumsum() < 80).sum()) + 1, len(muni_summary))
    out.append(f"<b>{n_munis_top80}</b> municipios concentran el 80% del peso económico registrado.")
    return out


def generate_opportunity_insights(opp_df: pd.DataFrame) -> list[str]:
    out = []
    if opp_df.empty:
        return out
    n_high = int((opp_df["nivel"] == "High").sum())
    pct_high = n_high / len(opp_df) * 100 if len(opp_df) else 0
    out.append(f"<b>{n_high}</b> AGEB ({pct_high:.0f}%) califican con Opportunity Score <b>High</b>.")
    top_ageb = opp_df.sort_values("opportunity_score", ascending=False).iloc[0]
    out.append(
        f"El AGEB con mayor oportunidad es <b>{top_ageb[AGEB_ID_COL]}</b> "
        f"(municipio {top_ageb['municipio']}), score <b>{top_ageb['opportunity_score']:.2f}</b>."
    )
    by_muni = opp_df.groupby("municipio")["opportunity_score"].mean().sort_values(ascending=False)
    if not by_muni.empty:
        out.append(
            f"El municipio con mayor oportunidad promedio es <b>{by_muni.index[0]}</b> "
            f"(score medio <b>{by_muni.iloc[0]:.2f}</b>)."
        )
    return out


# ══════════════════════════════════════════════════════════
# LAYER RENDERERS — misma interfaz, mismo mapa
# ══════════════════════════════════════════════════════════
@dataclass
class MapTraceSpec:
    traces: list
    legend_html: str
    id_col: str            # columna en customdata[...,0] usada para selección por click


@dataclass
class LayerBase:
    id: str
    label: str

    def available(self, ctx: SimpleNamespace) -> bool:
        return True

    def variable_options(self, ctx: SimpleNamespace) -> dict:
        return {}

    def build_map_traces(self, ctx: SimpleNamespace, variable_key: Optional[str]) -> MapTraceSpec:
        raise NotImplementedError

    def detail_panel(self, ctx: SimpleNamespace, selected_id) -> str:
        raise NotImplementedError

    def ranking(self, ctx: SimpleNamespace, variable_key: Optional[str]) -> pd.DataFrame:
        raise NotImplementedError

    def insights(self, ctx: SimpleNamespace, variable_key: Optional[str]) -> list[str]:
        return []


def _grad_legend(title: str, vmin: float, vmax: float, css_gradient: str) -> str:
    return f"""
    <div class="legend-card">
      <div class="legend-title">{title}</div>
      <div class="legend-grad" style="background:{css_gradient};"></div>
      <div class="legend-scale-row"><span>{_format_compact(vmin)}</span><span>{_format_compact(vmax)}</span></div>
    </div>
    """


def _categorical_legend(title: str, items: list[tuple[str, str]]) -> str:
    chips = "".join(
        f'<div class="legend-chip"><span class="dot" style="background:{color};"></span>{label}</div>'
        for label, color in items
    )
    return f"""
    <div class="legend-card">
      <div class="legend-title">{title}</div>
      <div class="legend-chip-row">{chips}</div>
    </div>
    """


# ── Layer 1 · Economic Communities ──────────────────────────────────────
class CommunityLayer(LayerBase):
    def __init__(self):
        super().__init__("community", "Economic Communities")

    def build_map_traces(self, ctx, variable_key):
        gdf = ctx.ageb_gdf_wgs84[ctx.ageb_gdf_wgs84["cluster_id"].isin(ctx.active_clusters)]
        traces = []
        for cid in sorted(gdf["cluster_id"].unique()):
            sub = gdf[gdf["cluster_id"] == cid]
            sub_geo = json.loads(sub.to_json())
            sel = ctx.selection.get(self.id)
            traces.append(go.Choroplethmapbox(
                geojson=sub_geo, locations=sub.index, z=[1] * len(sub),
                colorscale=[[0, ctx.color_by_cluster[cid]], [1, ctx.color_by_cluster[cid]]],
                showscale=False,
                marker_opacity=0.85 if (sel is None or sel == cid) else 0.25,
                marker_line_width=1.1 if sel == cid else 0.2,
                marker_line_color="#F4F5F7" if sel == cid else "#0B0F17",
                name=_short_name(ctx.nombre_by_cluster[cid]),
                customdata=np.column_stack([[cid] * len(sub), sub[AGEB_ID_COL], sub["municipio"]]),
                hovertemplate=(
                    f"<b>{_short_name(ctx.nombre_by_cluster[cid])}</b><br>"
                    "AGEB %{customdata[1]}<br>Municipio %{customdata[2]}<extra></extra>"
                ),
            ))
        items = [(_short_name(ctx.nombre_by_cluster[c]), ctx.color_by_cluster[c])
                 for c in sorted(gdf["cluster_id"].unique())][:10]
        legend = _categorical_legend("Comunidad económica dominante", items)
        return MapTraceSpec(traces, legend, id_col="cluster_id")

    def detail_panel(self, ctx, selected_id):
        summary = ctx.community_summary
        if selected_id is None or selected_id not in summary["cluster_id"].values:
            return None
        row = summary[summary["cluster_id"] == selected_id].iloc[0]
        sectores_txt = "".join(f'<span class="tag">{s}</span>' for s in row["sectores"][:12])
        municipios_txt = "".join(f'<span class="tag">Mun. {m}</span>' for m in row["municipios"][:12])
        html = f"""
        <div class="detail-sub">Comunidad {selected_id}</div>
        <div class="detail-title" style="color:{row['color']};">{_short_name(row['nombre'])}</div>
        <div class="detail-kpi-row">
          <div class="detail-kpi"><div class="detail-kpi-label">AGEBs</div><div class="detail-kpi-value">{row['n_agebs']}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Sectores</div><div class="detail-kpi-value">{row['n_sectores']}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Municipios</div><div class="detail-kpi-value">{row['n_municipios']}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Participación</div><div class="detail-kpi-value">{row['participacion_pct']:.1f}%</div></div>
        </div>
        <div class="section-label">Peso económico</div>
        <div class="detail-kpi-value">{_format_compact(row['peso_economico'])}</div>
        <div class="section-label">Sectores predominantes</div>
        <div class="tag-row">{sectores_txt}</div>
        <div class="section-label">Municipios presentes</div>
        <div class="tag-row">{municipios_txt}</div>
        """
        if ctx.shock_activo:
            srow = ctx.shock_by_cluster[ctx.shock_by_cluster["cluster_id"] == selected_id]
            if not srow.empty:
                srow = srow.iloc[0]
                html += f"""
                <div class="section-label">Impacto recibido (simulación cargada)</div>
                <div class="detail-kpi-row">
                  <div class="detail-kpi"><div class="detail-kpi-label">Directo</div><div class="detail-kpi-value">{_format_compact(srow[IMPACTO_DIRECTO_COL])}</div></div>
                  <div class="detail-kpi"><div class="detail-kpi-label">Indirecto</div><div class="detail-kpi-value">{_format_compact(srow[IMPACTO_INDIRECTO_COL])}</div></div>
                </div>
                <div class="detail-kpi" style="margin-top:8px;">
                  <div class="detail-kpi-label">Propagado</div><div class="detail-kpi-value">{_format_compact(srow[IMPACTO_PROPAGADO_COL])}</div>
                </div>
                """
        return html

    def ranking(self, ctx, variable_key):
        df = ctx.community_summary.copy()
        df["label"] = df["nombre"].map(_short_name)
        return df[["label", "participacion_pct"]].rename(columns={"participacion_pct": "value"})

    def insights(self, ctx, variable_key):
        out = generate_structural_insights(ctx.community_summary)
        if ctx.shock_activo:
            df = ctx.community_summary.merge(ctx.shock_by_cluster, on="cluster_id", how="left").fillna(0)
            df["label"] = df["nombre"].map(_short_name)
            out += generate_shock_insights_by_group(df, "label")
        return out


# ── Layer 2 · Propagation ───────────────────────────────────────────────
class PropagationLayer(LayerBase):
    def __init__(self):
        super().__init__("propagation", "Propagation Layer")

    def available(self, ctx):
        return ctx.shock_activo

    def variable_options(self, ctx):
        return {
            "Propagated Impact": IMPACTO_PROPAGADO_COL,
            "Spatial Spillover":  IMPACTO_INDIRECTO_COL,
            "Shock Intensity":    "_shock_intensity",
            "Decay Effect":       "_decay_effect",
        }

    def _prepared_gdf(self, ctx):
        sim = ctx.sim_gdf.copy()
        sim["_shock_intensity"] = sim[IMPACTO_DIRECTO_COL].abs()
        sim["_decay_effect"] = sim[IMPACTO_INDIRECTO_COL].abs() / (sim[IMPACTO_DIRECTO_COL].abs() + 1e-9)
        return sim

    def build_map_traces(self, ctx, variable_key):
        col = variable_key or IMPACTO_PROPAGADO_COL
        sim = self._prepared_gdf(ctx)
        try:
            sim_wgs = sim.to_crs(epsg=4326)
        except Exception:
            sim_wgs = sim
        sim_geo = json.loads(sim_wgs.to_json())
        vmin, vmax = float(sim_wgs[col].min()), float(sim_wgs[col].max())
        trace = go.Choroplethmapbox(
            geojson=sim_geo, locations=sim_wgs.index, z=sim_wgs[col],
            colorscale="Turbo", marker_opacity=0.82, marker_line_width=0.2,
            customdata=sim_wgs[[AGEB_ID_COL]].assign(_m=sim_wgs[AGEB_ID_COL].map(_municipio_code))[[AGEB_ID_COL, "_m"]].values,
            hovertemplate="AGEB %{customdata[0]}<br>Municipio %{customdata[1]}<br>Valor: %{z:,.2f}<extra></extra>",
            colorbar=dict(title=dict(text="", font=dict(size=9))),
        )
        legend = _grad_legend(
            [k for k, v in self.variable_options(ctx).items() if v == col][0],
            vmin, vmax, "linear-gradient(90deg,#30123b,#29bf12,#f9c80e)",
        )
        return MapTraceSpec([trace], legend, id_col=AGEB_ID_COL)

    def detail_panel(self, ctx, selected_id):
        sim = self._prepared_gdf(ctx)
        row = sim[sim[AGEB_ID_COL] == selected_id]
        if row.empty:
            return None
        row = row.iloc[0]
        html = f"""
        <div class="detail-sub">AGEB</div>
        <div class="detail-title">{row[AGEB_ID_COL]}</div>
        <div class="section-label">Municipio</div>
        <div class="detail-kpi-value">{_municipio_code(row[AGEB_ID_COL])}</div>
        <div class="detail-kpi-row">
          <div class="detail-kpi"><div class="detail-kpi-label">Propagated</div><div class="detail-kpi-value">{_format_compact(row[IMPACTO_PROPAGADO_COL])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Spillover</div><div class="detail-kpi-value">{_format_compact(row[IMPACTO_INDIRECTO_COL])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Shock Intensity</div><div class="detail-kpi-value">{_format_compact(row['_shock_intensity'])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Decay Effect</div><div class="detail-kpi-value">{row['_decay_effect']:.2f}</div></div>
        </div>
        """
        return html

    def ranking(self, ctx, variable_key):
        col = variable_key or IMPACTO_PROPAGADO_COL
        sim = self._prepared_gdf(ctx)
        df = pd.DataFrame(sim.drop(columns="geometry"))
        df["label"] = df[AGEB_ID_COL]
        return df[["label", col]].rename(columns={col: "value"}).reindex(
            df[col].abs().sort_values(ascending=False).index
        ).head(15)

    def insights(self, ctx, variable_key):
        sim = self._prepared_gdf(ctx)
        df = pd.DataFrame(sim.drop(columns="geometry"))
        out = []
        total = df[IMPACTO_PROPAGADO_COL].abs().sum()
        if total > 0:
            top = df.reindex(df[IMPACTO_PROPAGADO_COL].abs().sort_values(ascending=False).index).iloc[0]
            out.append(
                f"El AGEB <b>{top[AGEB_ID_COL]}</b> concentra el mayor impacto propagado: "
                f"<b>{top[IMPACTO_PROPAGADO_COL]/total*100:.0f}%</b> del total en la red espacial."
            )
        mean_decay = df["_decay_effect"].replace([np.inf, -np.inf], np.nan).mean()
        if pd.notna(mean_decay):
            out.append(f"El efecto de decaimiento (spillover / shock directo) promedio es de <b>{mean_decay:.2f}</b>.")
        return out


# ── Layer 3 · Impact ─────────────────────────────────────────────────────
class ImpactLayer(LayerBase):
    def __init__(self):
        super().__init__("impact", "Impact Layer")

    def available(self, ctx):
        return ctx.shock_activo

    def variable_options(self, ctx):
        return {
            "Direct Impact":   IMPACTO_DIRECTO_COL,
            "Indirect Impact": IMPACTO_INDIRECTO_COL,
            "Total Impact":    IMPACTO_PROPAGADO_COL,
        }

    def build_map_traces(self, ctx, variable_key):
        col = variable_key or IMPACTO_PROPAGADO_COL
        sim = ctx.sim_gdf
        try:
            sim_wgs = sim.to_crs(epsg=4326)
        except Exception:
            sim_wgs = sim
        sim_geo = json.loads(sim_wgs.to_json())
        vmin, vmax = float(sim_wgs[col].min()), float(sim_wgs[col].max())
        trace = go.Choroplethmapbox(
            geojson=sim_geo, locations=sim_wgs.index, z=sim_wgs[col],
            colorscale="Sunset", marker_opacity=0.82, marker_line_width=0.2,
            customdata=sim_wgs[[AGEB_ID_COL]].assign(_m=sim_wgs[AGEB_ID_COL].map(_municipio_code))[[AGEB_ID_COL, "_m"]].values,
            hovertemplate="AGEB %{customdata[0]}<br>Municipio %{customdata[1]}<br>Valor: %{z:,.2f}<extra></extra>",
        )
        legend = _grad_legend(
            [k for k, v in self.variable_options(ctx).items() if v == col][0],
            vmin, vmax, "linear-gradient(90deg,#2c115f,#c1447e,#fddb92)",
        )
        return MapTraceSpec([trace], legend, id_col=AGEB_ID_COL)

    def detail_panel(self, ctx, selected_id):
        sim_df = pd.DataFrame(ctx.sim_gdf.drop(columns="geometry"))
        row = sim_df[sim_df[AGEB_ID_COL] == selected_id]
        if row.empty:
            return None
        row = row.iloc[0]
        total_abs = sim_df[IMPACTO_PROPAGADO_COL].abs().sum()
        share = (abs(row[IMPACTO_PROPAGADO_COL]) / total_abs * 100) if total_abs else 0.0
        rank = int((sim_df[IMPACTO_PROPAGADO_COL].abs() > abs(row[IMPACTO_PROPAGADO_COL])).sum()) + 1
        html = f"""
        <div class="detail-sub">AGEB · sin agrupar por comunidad</div>
        <div class="detail-title">{row[AGEB_ID_COL]}</div>
        <div class="section-label">Municipio</div>
        <div class="detail-kpi-value">{_municipio_code(row[AGEB_ID_COL])}</div>
        <div class="detail-kpi-row">
          <div class="detail-kpi"><div class="detail-kpi-label">Impacto directo</div><div class="detail-kpi-value">{_format_compact(row[IMPACTO_DIRECTO_COL])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Impacto indirecto</div><div class="detail-kpi-value">{_format_compact(row[IMPACTO_INDIRECTO_COL])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Impacto total</div><div class="detail-kpi-value">{_format_compact(row[IMPACTO_PROPAGADO_COL])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Participación</div><div class="detail-kpi-value">{share:.2f}%</div></div>
        </div>
        <div class="section-label">Ranking</div>
        <div class="detail-kpi-value">#{rank} de {len(sim_df)} AGEB</div>
        """
        return html

    def ranking(self, ctx, variable_key):
        col = variable_key or IMPACTO_PROPAGADO_COL
        df = pd.DataFrame(ctx.sim_gdf.drop(columns="geometry"))
        df["label"] = df[AGEB_ID_COL]
        return df[["label", col]].rename(columns={col: "value"}).reindex(
            df[col].abs().sort_values(ascending=False).index
        ).head(15)

    def insights(self, ctx, variable_key):
        df = pd.DataFrame(ctx.sim_gdf.drop(columns="geometry"))
        out = []
        total = df[IMPACTO_PROPAGADO_COL].abs().sum()
        if total > 0:
            top3 = df.reindex(df[IMPACTO_PROPAGADO_COL].abs().sort_values(ascending=False).index).head(3)
            out.append(
                f"Los 3 AGEB más impactados concentran el "
                f"<b>{top3[IMPACTO_PROPAGADO_COL].abs().sum()/total*100:.0f}%</b> del impacto total."
            )
        share_directo = df[IMPACTO_DIRECTO_COL].abs().sum() / total * 100 if total else 0
        out.append(f"El impacto directo representa el <b>{share_directo:.0f}%</b> del impacto total; "
                    f"el resto es propagación espacial indirecta.")
        return out


# ── Layer 4 · Municipality ──────────────────────────────────────────────
class MunicipalityLayer(LayerBase):
    def __init__(self):
        super().__init__("municipality", "Municipality Layer")

    def variable_options(self, ctx):
        opts = {"Cluster dominante": None, "Peso económico": "peso", "Participación": "participacion_pct"}
        if ctx.shock_activo:
            opts["Impacto agregado"] = IMPACTO_PROPAGADO_COL
        return opts

    def build_map_traces(self, ctx, variable_key):
        gdf = ctx.muni_gdf_wgs84
        traces = []
        sel = ctx.selection.get(self.id)
        if variable_key is None:  # categórico por cluster dominante
            for cid in sorted(gdf["cluster_dominante"].dropna().unique()):
                sub = gdf[gdf["cluster_dominante"] == cid]
                sub_geo = json.loads(sub.to_json())
                color = ctx.color_by_cluster.get(int(cid), "#576073")
                traces.append(go.Choroplethmapbox(
                    geojson=sub_geo, locations=sub.index, z=[1] * len(sub),
                    colorscale=[[0, color], [1, color]], showscale=False,
                    marker_opacity=0.85 if (sel is None or sel in sub["municipio"].values) else 0.3,
                    marker_line_width=0.3, name=_short_name(ctx.nombre_by_cluster.get(int(cid), f"Cluster {cid}")),
                    customdata=sub[["municipio"]].values,
                    hovertemplate="Municipio %{customdata[0]}<extra></extra>",
                ))
            items = [(_short_name(ctx.nombre_by_cluster.get(int(c), f"C{c}")), ctx.color_by_cluster.get(int(c), "#576073"))
                     for c in sorted(gdf["cluster_dominante"].dropna().unique())][:10]
            legend = _categorical_legend("Cluster dominante por municipio", items)
        else:
            vmin, vmax = float(gdf[variable_key].min()), float(gdf[variable_key].max())
            geo = json.loads(gdf.to_json())
            traces.append(go.Choroplethmapbox(
                geojson=geo, locations=gdf.index, z=gdf[variable_key],
                colorscale="Blues", marker_opacity=0.85, marker_line_width=0.3,
                customdata=gdf[["municipio"]].values,
                hovertemplate="Municipio %{customdata[0]}<br>Valor: %{z:,.2f}<extra></extra>",
            ))
            legend = _grad_legend(variable_key, vmin, vmax, "linear-gradient(90deg,#0d2b52,#3b82f6,#bfdbfe)")
        return MapTraceSpec(traces, legend, id_col="municipio")

    def detail_panel(self, ctx, selected_id):
        df = ctx.muni_summary
        row = df[df["municipio"] == selected_id]
        if row.empty:
            return None
        row = row.iloc[0]
        html = f"""
        <div class="detail-sub">Municipio</div>
        <div class="detail-title">{row['municipio']}</div>
        <div class="detail-kpi-row">
          <div class="detail-kpi"><div class="detail-kpi-label">AGEBs</div><div class="detail-kpi-value">{int(row['n_agebs'])}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Participación</div><div class="detail-kpi-value">{row['participacion_pct']:.1f}%</div></div>
        </div>
        <div class="section-label">Cluster dominante</div>
        <div class="tag-row"><span class="tag" style="color:{row['color']}; border-color:{row['color']};">{_short_name(row['cluster_dominante_nombre'])}</span></div>
        <div class="section-label">Peso económico</div>
        <div class="detail-kpi-value">{_format_compact(row['peso'])}</div>
        """
        if ctx.shock_activo and IMPACTO_PROPAGADO_COL in row:
            html += f"""
            <div class="section-label">Impacto agregado (simulación cargada)</div>
            <div class="detail-kpi-row">
              <div class="detail-kpi"><div class="detail-kpi-label">Directo</div><div class="detail-kpi-value">{_format_compact(row.get(IMPACTO_DIRECTO_COL, 0))}</div></div>
              <div class="detail-kpi"><div class="detail-kpi-label">Propagado</div><div class="detail-kpi-value">{_format_compact(row.get(IMPACTO_PROPAGADO_COL, 0))}</div></div>
            </div>
            """
        return html

    def ranking(self, ctx, variable_key):
        col = variable_key or "participacion_pct"
        df = ctx.muni_summary.copy()
        df["label"] = "Mun. " + df["municipio"].astype(str)
        return df[["label", col]].rename(columns={col: "value"}).head(15)

    def insights(self, ctx, variable_key):
        out = generate_municipality_insights(ctx.muni_summary)
        if ctx.shock_activo and IMPACTO_PROPAGADO_COL in ctx.muni_summary.columns:
            df = ctx.muni_summary.copy()
            df["label"] = "Municipio " + df["municipio"].astype(str)
            out += generate_shock_insights_by_group(df, "label")
        return out


# ── Layer 5 · Infrastructure (placeholder preparado) ────────────────────
class InfrastructureLayer(LayerBase):
    def __init__(self):
        super().__init__("infrastructure", "Infrastructure Layer (soon)")

    def build_map_traces(self, ctx, variable_key):
        return MapTraceSpec([], "", id_col=AGEB_ID_COL)

    def detail_panel(self, ctx, selected_id):
        return None

    def ranking(self, ctx, variable_key):
        return pd.DataFrame(columns=["label", "value"])

    def insights(self, ctx, variable_key):
        return []


# ── Layer 6 · Opportunity ────────────────────────────────────────────────
class OpportunityLayer(LayerBase):
    def __init__(self):
        super().__init__("opportunity", "Opportunity Layer")

    def build_map_traces(self, ctx, variable_key):
        gdf = ctx.opp_gdf_wgs84
        geo = json.loads(gdf.to_json())
        vmin, vmax = 0.0, 1.0
        trace = go.Choroplethmapbox(
            geojson=geo, locations=gdf.index, z=gdf["opportunity_score"],
            colorscale=[[0, "#576073"], [0.5, "#F5B942"], [1, "#34D399"]],
            zmin=0, zmax=1, marker_opacity=0.85, marker_line_width=0.2,
            customdata=gdf[[AGEB_ID_COL, "municipio", "nivel"]].values,
            hovertemplate=(
                "AGEB %{customdata[0]}<br>Municipio %{customdata[1]}<br>"
                "Score: %{z:.2f} (%{customdata[2]})<extra></extra>"
            ),
        )
        legend = _grad_legend("Opportunity Score", vmin, vmax, "linear-gradient(90deg,#576073,#F5B942,#34D399)")
        return MapTraceSpec([trace], legend, id_col=AGEB_ID_COL)

    def detail_panel(self, ctx, selected_id):
        df = ctx.opp_df
        row = df[df[AGEB_ID_COL] == selected_id]
        if row.empty:
            return None
        row = row.iloc[0]
        level_cls = {"High": "level-high", "Medium": "level-medium", "Low": "level-low"}[row["nivel"]]
        html = f"""
        <div class="detail-sub">AGEB · Opportunity Score</div>
        <div class="detail-title">{row[AGEB_ID_COL]}</div>
        <div class="tag-row"><span class="tag {level_cls}">{row['nivel']}</span>
          <span class="tag">Score {row['opportunity_score']:.2f}</span></div>
        <div class="section-label">Componentes normalizados (0–1)</div>
        <div class="detail-kpi-row">
          <div class="detail-kpi"><div class="detail-kpi-label">Impacto</div><div class="detail-kpi-value">{row['impacto_economico_norm']:.2f}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Participación</div><div class="detail-kpi-value">{row['participacion_norm']:.2f}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Centralidad</div><div class="detail-kpi-value">{row['centralidad_norm']:.2f}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Diversidad</div><div class="detail-kpi-value">{row['diversidad_norm']:.2f}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Especialización</div><div class="detail-kpi-value">{row['especializacion_norm']:.2f}</div></div>
          <div class="detail-kpi"><div class="detail-kpi-label">Cobertura</div><div class="detail-kpi-value">{row['cobertura_norm']:.2f}</div></div>
        </div>
        <div class="section-label">Fuente del componente "Impacto"</div>
        <div class="detail-kpi-value" style="font-size:12px;">{row['impacto_fuente']}</div>
        """
        return html

    def ranking(self, ctx, variable_key):
        df = ctx.opp_df.copy()
        df["label"] = df[AGEB_ID_COL]
        return df[["label", "opportunity_score"]].rename(columns={"opportunity_score": "value"}).sort_values(
            "value", ascending=False
        ).head(15)

    def insights(self, ctx, variable_key):
        return generate_opportunity_insights(ctx.opp_df)


LAYERS: dict[str, LayerBase] = {
    l.id: l for l in [
        CommunityLayer(), PropagationLayer(), ImpactLayer(),
        MunicipalityLayer(), InfrastructureLayer(), OpportunityLayer(),
    ]
}
LAYER_ORDER = ["community", "propagation", "impact", "municipality", "infrastructure", "opportunity"]


# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
st.markdown('<div class="kicker">◈ SPATIAL CLUSTER INTELLIGENCE</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Comunidades Económicas Territoriales</div>', unsafe_allow_html=True)
_md("""
<div class="subtitle">Cómo está organizada espacialmente la economía — 6 formas de leer el mismo territorio.</div>
""")
st.markdown('<hr class="thin">', unsafe_allow_html=True)

artifact = load_cluster_artifact()
if artifact is None:
    _md(f"""
    <div class="empty-state">
      <div style="font-size:1.1rem; font-weight:700; color:var(--text); margin-bottom:8px;">
        No se encontró el artefacto de comunidades económicas
      </div>
      <div>Corre: <code>python -m scripts.build_sector_clusters</code></div>
    </div>
    """)
    st.stop()

warehouse_gdf = load_warehouse_gdf()
if warehouse_gdf is None:
    _md(f"""
    <div class="empty-state">
      <div style="font-size:1.1rem; font-weight:700; color:var(--text); margin-bottom:8px;">
        Warehouse espacial no disponible
      </div>
      <div>No se encontró <code>{Path(WAREHOUSE_PARQUET).relative_to(_REPO_ROOT)}</code> (Stage 5).</div>
    </div>
    """)
    st.stop()

ageb_gdf, long_df, integrity_report = build_ageb_community_gdf(warehouse_gdf, artifact)
if ageb_gdf.empty:
    st.error("Ningún AGEB del warehouse tiene un sector mapeado a una comunidad.")
    st.stop()
_compute_sector_diversity(
    pd.DataFrame(warehouse_gdf.drop(columns="geometry")).assign(
        **{SECTOR_COL: pd.DataFrame(warehouse_gdf.drop(columns="geometry"))[SECTOR_COL].astype(str)}
    ).groupby(AGEB_ID_COL)[SECTOR_COL].nunique().rename("n_sectores_ageb").reset_index()
)

community_summary = build_community_summary(ageb_gdf, artifact)
sim_gdf = get_simulation_gdf()
shock_activo = sim_gdf is not None

shock_by_cluster, shock_cov_cluster = (None, {})
if shock_activo:
    shock_by_cluster, shock_cov_cluster = aggregate_shock_by(
        sim_gdf, ageb_gdf[[AGEB_ID_COL, "cluster_id"]], "cluster_id"
    )

muni_gdf, muni_cluster_weights = build_municipality_gdf(ageb_gdf, long_df)
shock_by_muni, shock_cov_muni = (None, {})
if shock_activo:
    shock_by_muni, shock_cov_muni = aggregate_shock_by(
        sim_gdf, ageb_gdf[[AGEB_ID_COL, "municipio"]], "municipio"
    )
muni_summary = build_municipality_summary(muni_gdf, community_summary, shock_by_muni)

if "opportunity_weights" not in st.session_state:
    st.session_state["opportunity_weights"] = dict(DEFAULT_OPPORTUNITY_WEIGHTS)

opp_df = build_opportunity_scores(
    ageb_gdf, long_df, community_summary, integrity_report["n_sectores_en_warehouse"],
    sim_gdf, st.session_state["opportunity_weights"],
)

if "selection" not in st.session_state:
    st.session_state["selection"] = {}
if "active_communities" not in st.session_state:
    st.session_state["active_communities"] = set(community_summary["cluster_id"].tolist())

color_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["color"]))
nombre_by_cluster = dict(zip(community_summary["cluster_id"], community_summary["nombre"]))

try:
    ageb_gdf_wgs84 = ageb_gdf.to_crs(epsg=4326)
except Exception:
    ageb_gdf_wgs84 = ageb_gdf
try:
    muni_gdf_wgs84 = muni_gdf.to_crs(epsg=4326)
except Exception:
    muni_gdf_wgs84 = muni_gdf

opp_gdf = ageb_gdf.merge(
    opp_df[[AGEB_ID_COL, "opportunity_score", "nivel"] + [c for c in opp_df.columns if c.endswith("_norm")] + ["impacto_fuente"]],
    on=AGEB_ID_COL, how="inner",
)
try:
    opp_gdf_wgs84 = opp_gdf.to_crs(epsg=4326)
except Exception:
    opp_gdf_wgs84 = opp_gdf

ctx = SimpleNamespace(
    artifact=artifact, ageb_gdf=ageb_gdf, ageb_gdf_wgs84=ageb_gdf_wgs84, long_df=long_df,
    community_summary=community_summary, color_by_cluster=color_by_cluster, nombre_by_cluster=nombre_by_cluster,
    shock_activo=shock_activo, sim_gdf=sim_gdf, shock_by_cluster=shock_by_cluster,
    muni_gdf=muni_gdf, muni_gdf_wgs84=muni_gdf_wgs84, muni_summary=muni_summary,
    opp_df=opp_df, opp_gdf_wgs84=opp_gdf_wgs84,
    active_clusters=st.session_state["active_communities"], selection=st.session_state["selection"],
)

# ══════════════════════════════════════════════════════════
# TOOLBAR — capas + variable + búsqueda + estado de simulación
# ══════════════════════════════════════════════════════════
tb1, tb2, tb3 = st.columns([1.9, 1.6, 1])
with tb1:
    labels = [LAYERS[k].label for k in LAYER_ORDER]
    layer_label = st.radio("Layer", labels, horizontal=True, label_visibility="collapsed", key="layer_sel")
    active_layer_id = LAYER_ORDER[labels.index(layer_label)]
with tb2:
    query = st.text_input(
        "Buscar AGEB, municipio, sector o comunidad", placeholder="🔎 Buscar AGEB, municipio, sector o comunidad…",
        label_visibility="collapsed",
    )
with tb3:
    if shock_activo:
        st.markdown('<div class="insight-card shock" style="margin:0;">◆ Shock cargado — impacto disponible</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="insight-card" style="margin:0; opacity:.7;">Sin simulación — capas de impacto limitadas</div>', unsafe_allow_html=True)

layer = LAYERS[active_layer_id]

if not layer.available(ctx):
    st.info(f"'{layer.label}' requiere una simulación cargada en Run Simulation. Mostrando Economic Communities mientras tanto.")
    layer = LAYERS["community"]
    active_layer_id = "community"

variable_key = None
var_opts = layer.variable_options(ctx)
if var_opts:
    vsel1, _ = st.columns([1, 3])
    with vsel1:
        var_label = st.selectbox("Variable", list(var_opts.keys()), key=f"var_{active_layer_id}")
    variable_key = var_opts[var_label]

# ── Resolución de búsqueda (funciona en todas las Layers) ──────────────
matched_clusters: set[int] = set()
matched_ageb: Optional[str] = None
matched_muni: Optional[str] = None
if query.strip():
    q = query.strip().lower()
    for _, row in community_summary.iterrows():
        if q in row["nombre"].lower() or any(q in s.lower() for s in row["sectores"]) or any(q in m.lower() for m in row["municipios"]):
            matched_clusters.add(row["cluster_id"])
    ageb_hits = ageb_gdf[ageb_gdf[AGEB_ID_COL].str.lower().str.contains(q, na=False)]
    if ageb_hits[AGEB_ID_COL].nunique() == 1:
        matched_ageb = ageb_hits.iloc[0][AGEB_ID_COL]
    muni_hits = [m for m in muni_summary["municipio"].unique() if q in str(m).lower()]
    if len(muni_hits) == 1:
        matched_muni = muni_hits[0]

    if active_layer_id == "community" and len(matched_clusters) == 1:
        st.session_state["selection"]["community"] = next(iter(matched_clusters))
    elif active_layer_id == "municipality" and matched_muni is not None:
        st.session_state["selection"]["municipality"] = matched_muni
    elif active_layer_id in ("propagation", "impact", "opportunity") and matched_ageb is not None:
        st.session_state["selection"][active_layer_id] = matched_ageb
    ctx.selection = st.session_state["selection"]

# ══════════════════════════════════════════════════════════
# LAYOUT — 3 columnas: comunidades (filtro global) · mapa · detalle
# ══════════════════════════════════════════════════════════
col_list, col_map, col_detail = st.columns([1.05, 2.6, 1.15])

with col_list:
    st.markdown('<div class="section-label">Comunidades (filtro global)</div>', unsafe_allow_html=True)
    active = st.session_state["active_communities"]
    for _, row in community_summary.iterrows():
        cid = row["cluster_id"]
        is_selected = st.session_state["selection"].get("community") == cid
        is_active = cid in active
        dim_cls = "" if (not query.strip() or cid in matched_clusters or not matched_clusters) else "dim"
        card_cls = f"community-card {'active' if is_selected else ''} {dim_cls}".strip()
        _md(f"""
        <div class="{card_cls}">
          <div class="cc-head">
            <div class="cc-dot" style="background:{row['color']};"></div>
            <div class="cc-name">{_short_name(row['nombre'])}</div>
          </div>
          <div class="cc-meta">{row['n_agebs']} AGEB · {row['n_sectores']} sectores · {row['participacion_pct']:.1f}% part.</div>
        </div>
        """)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Seleccionar", key=f"sel_{cid}", use_container_width=True):
                st.session_state["selection"]["community"] = cid
                st.rerun()
        with b2:
            toggle_label = "Ocultar" if is_active else "Mostrar"
            if st.button(toggle_label, key=f"tgl_{cid}", use_container_width=True):
                active.discard(cid) if is_active else active.add(cid)
                st.session_state["active_communities"] = active
                st.rerun()

with col_map:
    trace_spec = layer.build_map_traces(ctx, variable_key)
    if not trace_spec.traces:
        if active_layer_id == "infrastructure":
            _md("""
            <div class="empty-state">
              <div style="font-size:1.1rem; font-weight:700; color:var(--text); margin-bottom:8px;">
                Infrastructure Layer — próximamente
              </div>
              <div>La arquitectura está lista: en cuanto se coloque un GeoJSON en
              <code>data/analytics/infrastructure/&lt;fuente&gt;.geojson</code>, la capa correspondiente
              se activa automáticamente, sin cambios de código.</div>
            </div>
            """)
            for key, meta in INFRASTRUCTURE_SOURCES.items():
                ready = (INFRASTRUCTURE_DIR / meta["file"]).exists()
                status = '<span class="ready">● listo para conectar</span>' if not ready else '<span class="ready">● cargado</span>'
                _md(f"""
                <div class="soon-card"><span class="icon">{meta['icon']}</span>{meta['label']}
                  <span class="pending">próximamente</span></div>
                """)
        else:
            st.markdown('<div class="empty-state">No hay datos para mostrar en esta capa.</div>', unsafe_allow_html=True)
    else:
        centroid = ageb_gdf_wgs84.geometry.union_all().centroid
        fig = go.Figure(data=trace_spec.traces)
        fig.update_layout(
            mapbox_style="carto-darkmatter", mapbox_zoom=8.2,
            mapbox_center={"lat": centroid.y, "lon": centroid.x},
            margin=dict(l=0, r=0, t=0, b=0), height=600,
            paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17",
            font=dict(family="Inter", color="#F4F5F7", size=11),
            legend=dict(bgcolor="rgba(16,21,31,0.85)", bordercolor="#212B3B", borderwidth=1,
                        font=dict(size=10), itemsizing="constant"),
            hoverlabel=dict(bgcolor="#171F2C", bordercolor="#212B3B", font=dict(color="#F4F5F7")),
            coloraxis_showscale=False,
        )
        map_event = st.plotly_chart(
            fig, use_container_width=True, config={"scrollZoom": True, "displaylogo": False},
            on_select="rerun", selection_mode=("points",), key=f"map_{active_layer_id}",
        )
        if map_event and map_event.get("selection", {}).get("points"):
            pt = map_event["selection"]["points"][0]
            cdata = pt.get("customdata")
            if cdata:
                clicked_id = cdata[0]
                if trace_spec.id_col == "cluster_id":
                    clicked_id = int(clicked_id)
                st.session_state["selection"][active_layer_id] = clicked_id
                st.rerun()
        _md(trace_spec.legend_html)

with col_detail:
    st.markdown('<div class="section-label">Detalle</div>', unsafe_allow_html=True)
    sel_id = st.session_state["selection"].get(active_layer_id)
    html = layer.detail_panel(ctx, sel_id) if sel_id is not None else None
    if html is None:
        st.markdown('<div class="detail-empty">Selecciona un elemento en el mapa o en la lista para ver su detalle.</div>', unsafe_allow_html=True)
    else:
        _md(f'<div class="detail-panel">{html}</div>')

# ══════════════════════════════════════════════════════════
# INSIGHTS (reglas, sin IA) — dependen de la Layer activa
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Hallazgos</div>', unsafe_allow_html=True)
insight_cls = "opportunity" if active_layer_id == "opportunity" else ("shock" if active_layer_id in ("propagation", "impact") else "")
for txt in layer.insights(ctx, variable_key):
    _md(f'<div class="insight-card {insight_cls}">{txt}</div>')

# ══════════════════════════════════════════════════════════
# RANKING — mismo componente reutilizado por todas las Layers
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Ranking</div>', unsafe_allow_html=True)
rk1, rk2 = st.columns(2)
with rk1:
    rank_df = layer.ranking(ctx, variable_key)
    if not rank_df.empty:
        rank_df = rank_df.reindex(rank_df["value"].abs().sort_values(ascending=True).index).tail(12)
        fig_rank = px.bar(
            rank_df, x="value", y="label", orientation="h", color="value",
            color_continuous_scale="Blues", title=f"Ranking — {layer.label}",
            labels={"value": "", "label": ""},
        )
        fig_rank.update_layout(
            height=380, paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17", font_color="#F4F5F7",
            margin=dict(l=0, r=0, t=40, b=0), title_font_size=12, coloraxis_showscale=False,
        )
        st.plotly_chart(fig_rank, use_container_width=True)
    else:
        st.info("Sin datos de ranking para esta capa.")

with rk2:
    if active_layer_id == "community":
        df_tree = community_summary.copy()
        df_tree["nombre_corto"] = df_tree["nombre"].map(_short_name)
        fig_tree = px.treemap(
            df_tree, path=["nombre_corto"], values="peso_economico", color="participacion_pct",
            color_continuous_scale="Blues", title="Peso económico por comunidad",
        )
        fig_tree.update_layout(height=380, paper_bgcolor="#0B0F17", font_color="#F4F5F7",
                                margin=dict(l=0, r=0, t=40, b=0), title_font_size=12)
        st.plotly_chart(fig_tree, use_container_width=True)
    elif active_layer_id == "opportunity":
        fig_hist = px.histogram(
            opp_df, x="opportunity_score", color="nivel",
            color_discrete_map=_LEVEL_COLOR, nbins=20, title="Distribución del Opportunity Score",
        )
        fig_hist.update_layout(height=380, paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17", font_color="#F4F5F7",
                                margin=dict(l=0, r=0, t=40, b=0), title_font_size=12)
        st.plotly_chart(fig_hist, use_container_width=True)
    elif active_layer_id == "municipality":
        fig_muni = px.bar(
            muni_summary.sort_values("n_agebs", ascending=True).tail(12),
            x="n_agebs", y="municipio", orientation="h", color="n_agebs",
            color_continuous_scale="Purples", title="AGEBs por municipio",
        )
        fig_muni.update_layout(height=380, paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17", font_color="#F4F5F7",
                                margin=dict(l=0, r=0, t=40, b=0), title_font_size=12, coloraxis_showscale=False)
        st.plotly_chart(fig_muni, use_container_width=True)
    elif active_layer_id in ("propagation", "impact") and shock_activo:
        sim_df_plot = pd.DataFrame(sim_gdf.drop(columns="geometry"))
        fig_dist = px.histogram(
            sim_df_plot, x=IMPACTO_PROPAGADO_COL, title="Distribución del impacto propagado", nbins=25,
        )
        fig_dist.update_layout(height=380, paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17", font_color="#F4F5F7",
                                margin=dict(l=0, r=0, t=40, b=0), title_font_size=12)
        st.plotly_chart(fig_dist, use_container_width=True)
    else:
        st.info("Sin visualización secundaria adicional para esta capa.")

# ══════════════════════════════════════════════════════════
# AJUSTES DEL OPPORTUNITY SCORE (solo visibles en esa Layer)
# ══════════════════════════════════════════════════════════
if active_layer_id == "opportunity":
    with st.expander("⚙️ Ajustar pesos del índice (suma no necesita ser 100 — se normaliza)"):
        cols = st.columns(3)
        new_weights = {}
        for i, (k, v) in enumerate(DEFAULT_OPPORTUNITY_WEIGHTS.items()):
            with cols[i % 3]:
                new_weights[k] = st.slider(k.replace("_", " ").title(), 0.0, 1.0,
                                            st.session_state["opportunity_weights"].get(k, v), 0.05, key=f"w_{k}")
        if st.button("Aplicar pesos"):
            st.session_state["opportunity_weights"] = new_weights
            st.rerun()

# ══════════════════════════════════════════════════════════
# INTEGRIDAD DE DATOS
# ══════════════════════════════════════════════════════════
with st.expander("🔍 Trazabilidad e integridad de datos"):
    st.markdown(f"""
    - Artefacto de comunidades: `{SECTOR_CLUSTER_JSON.relative_to(_REPO_ROOT)}` generado {artifact['generated_at']}
      · {artifact['n_clusters']} comunidades · modularidad Q={artifact['modularity']}
    - AGEBs asignados a una comunidad: **{integrity_report['n_agebs_asignados']}**
      · sin asignación: **{integrity_report['n_agebs_sin_asignacion']}**
    - Municipios detectados: **{muni_summary['municipio'].nunique()}**
    """)
    if integrity_report["sectores_no_mapeados"]:
        st.warning(
            f"{integrity_report['n_registros_sector_no_mapeado']} registros del warehouse pertenecen a "
            f"sectores sin comunidad asignada: {integrity_report['sectores_no_mapeados']}"
        )
    if shock_activo:
        st.caption(
            f"Cobertura shock↔comunidad: {shock_cov_cluster.get('n_agebs_con_grupo_y_shock', 0)} AGEB · "
            f"sin comunidad: {shock_cov_cluster.get('n_agebs_shock_sin_grupo', 0)}. "
            f"Cobertura shock↔municipio: {shock_cov_muni.get('n_agebs_con_grupo_y_shock', 0)} AGEB · "
            f"sin municipio: {shock_cov_muni.get('n_agebs_shock_sin_grupo', 0)}."
        )
    st.caption(
        "Opportunity Score: índice compuesto normalizado (min-max) sobre peso económico/impacto, "
        "participación, centralidad Louvain, diversidad/especialización de la mezcla de comunidades "
        "por AGEB y cobertura sectorial. Pesos por defecto y ajustables arriba. No usa IA ni ML."
    )
    st.download_button(
        "⬇ Descargar resumen de comunidades (CSV)",
        community_summary.drop(columns=["sectores", "municipios"]).to_csv(index=False).encode("utf-8"),
        "spatial_cluster_intelligence_communities.csv", "text/csv",
    )
    st.download_button(
        "⬇ Descargar resumen municipal (CSV)",
        muni_summary.drop(columns=[c for c in ["geometry"] if c in muni_summary.columns]).to_csv(index=False).encode("utf-8"),
        "spatial_cluster_intelligence_municipalities.csv", "text/csv",
    )
    st.download_button(
        "⬇ Descargar Opportunity Score por AGEB (CSV)",
        opp_df.drop(columns=[c for c in ["geometry"] if c in opp_df.columns]).to_csv(index=False).encode("utf-8"),
        "spatial_cluster_intelligence_opportunity.csv", "text/csv",
    )