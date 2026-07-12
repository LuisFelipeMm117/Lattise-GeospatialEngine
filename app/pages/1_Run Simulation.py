# app/pages/1_Run Simulation.py
"""
Lattise Studio — Run Simulation
Orquesta exclusivamente las APIs públicas ya cerradas del motor:
    serio.loader.ModeloEconomico.simular()
    spatial.simulation.engine.run_simulation_engine()
No recalcula Warehouse, Graph, SEE ni SERIO. No contiene lógica económica.

Sprint UX/UI — GIS profesional (ArcGIS Pro / CARTO / Palantir Foundry):
Todo lo agregado en este sprint es presentación pura sobre columnas ya
producidas por el motor (IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL,
IMPACTO_PROPAGADO_COL, geometry). No se recalcula, reinterpreta ni agrega
ninguna magnitud económica nueva. Los selectores de "variable", "color" y
"basemap" únicamente cambian cómo se visualizan columnas existentes;
el toggle de "capa" solo alterna el estilo del choropleth (on/off), no
los datos. Todo dato mostrado en KPIs, insights y rankings ya existía en
`gdf` / `report` — aquí solo se ordena, formatea y agrupa visualmente.
"""
import io
import json
import sys
import textwrap
import time
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Resolución de rutas del repo (app/pages/ → app/ → repo root) ───────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from serio.loader import ModeloEconomico
from spatial.config import AGEB_ID_COL
from spatial.simulation.engine import (
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
    run_simulation_engine,
)

st.set_page_config(
    page_title="Run Simulation — Lattise Studio",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════
# CSS — lenguaje visual GIS profesional
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

:root {
    --bg:        #0B0F17;
    --panel:     #10151F;
    --panel-hi:  #171F2C;
    --border:    #212B3B;
    --border-lo: #1A2230;
    --text:      #F4F5F7;
    --muted:     #8A93A6;
    --muted-dim: #576073;
    --accent:    #5B8DEF;
    --accent-soft: rgba(91,141,239,0.10);
    --ok:        #34D399;
    --warn:      #F5B942;
}

html, body, .stApp { background: var(--bg) !important; }
* { font-family: 'Inter', sans-serif; }

header {visibility: hidden;}
[data-testid="stToolbar"]     {display: none;}
[data-testid="stDecoration"]  {display: none;}
[data-testid="stStatusWidget"]{display: none;}
footer {visibility: hidden;}
#MainMenu {visibility: hidden;}

.block-container {
    max-width: 1400px;
    padding-top: 1.6rem;
    padding-bottom: 3rem;
}

/* ── Encabezado ───────────────────────────────────────────── */
.kicker {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--accent);
}
.page-title {
    font-size: 1.9rem;
    font-weight: 800;
    letter-spacing: -0.8px;
    color: var(--text);
    margin: 2px 0 0 0;
}
.pipeline-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: 'Space Mono', monospace;
    font-size: 10.5px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    background: var(--panel-hi);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 6px 14px 6px 10px;
    float: right;
    margin-top: 4px;
}
.dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 6px var(--ok);
    flex-shrink: 0;
}
.dot.busy { background: var(--warn); box-shadow: 0 0 6px var(--warn); }

hr.thin { border: none; border-top: 1px solid var(--border-lo); margin: 16px 0 20px 0; }

/* ── Toolbar de escenario (GIS command bar) ──────────────────── */
.toolbar-wrap {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 18px 4px 18px;
    margin-bottom: 18px;
}
.toolbar-label {
    font-family: 'Space Mono', monospace;
    font-size: 9.5px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--muted-dim);
    margin-bottom: -2px;
}
[data-testid="stSelectbox"] > div > div,
[data-testid="stNumberInput"] > div > div {
    background: var(--panel-hi) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
    min-height: 38px !important;
}
[data-testid="stSelectbox"] label,
[data-testid="stNumberInput"] label,
[data-testid="stSlider"] label {
    color: var(--muted) !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    letter-spacing: 0.3px;
}
[data-testid="stSlider"] div[data-baseweb="slider"] > div > div {
    background: var(--accent) !important;
}

div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button {
    border-radius: 8px;
    font-weight: 600;
    font-size: 13.5px;
    padding: 9px 18px;
    border: 1px solid var(--accent);
    transition: all 0.15s ease;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: var(--accent);
    color: white;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #4A78D6;
    border-color: #4A78D6;
}
div[data-testid="stDownloadButton"] > button,
div[data-testid="stButton"] > button[kind="secondary"] {
    background: var(--panel-hi);
    color: var(--muted);
    border: 1px solid var(--border);
    font-size: 12.5px;
    padding: 8px 14px;
}
div[data-testid="stDownloadButton"] > button:hover,
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    border-color: var(--accent);
    color: var(--accent);
}

/* ── Badges / chips de escenario ─────────────────────────────── */
.chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px 0; }
.chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--panel-hi);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 5px 13px;
    font-size: 12px;
    color: var(--text);
}
.chip b { color: var(--muted); font-weight: 500; margin-right: 2px; }
.chip.accent { border-color: var(--accent); color: var(--accent); }

/* ── Executive summary ───────────────────────────────────────── */
.exec-summary {
    color: var(--muted);
    font-size: 15px;
    line-height: 1.65;
    max-width: 980px;
    margin: 6px 0 22px 0;
}
.exec-summary strong { color: var(--text); font-weight: 600; }

/* ── GIS viewport ─────────────────────────────────────────────── */
.section-label {
    font-family: 'Space Mono', monospace;
    font-size: 10px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: var(--muted-dim);
    margin: 34px 0 12px 0;
}
.map-toolbar {
    display: flex; align-items: center; gap: 18px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: 14px 14px 0 0;
    padding: 10px 16px;
}
.map-card {
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 14px 14px;
    padding: 0;
    background: #0D1219;
    position: relative;
    overflow: hidden;
}
.map-placeholder {
    border: 1px dashed var(--border);
    border-radius: 14px;
    padding: 120px 20px;
    text-align: center;
    color: var(--muted-dim);
    font-size: 13.5px;
    background: rgba(255,255,255,0.012);
}
.map-toolbar [data-testid="stSelectbox"] > div > div {
    min-height: 32px !important;
    font-size: 12px !important;
}
.map-toolbar [data-testid="stSelectbox"] label { display: none !important; }
.layer-toggle-label {
    font-size: 11.5px; color: var(--muted); white-space: nowrap;
}

.floating-legend-wrap { display: flex; justify-content: flex-end; pointer-events: none; }
.floating-legend {
    pointer-events: auto;
    width: 208px;
    background: rgba(16,21,31,0.86);
    backdrop-filter: blur(6px);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    margin: 16px 16px 0 0;
    font-size: 11.5px;
    color: var(--muted);
}
.floating-legend .lg-title {
    font-family: 'Space Mono', monospace;
    font-size: 9.5px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted-dim);
    margin-bottom: 8px;
}
.legend-gradient {
    height: 8px; border-radius: 4px; margin-bottom: 4px;
}
.legend-scale-row { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted-dim); }
.fullscreen-chip {
    pointer-events: auto;
    width: fit-content;
    background: rgba(16,21,31,0.86);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
    color: var(--muted);
    margin: 16px 0 0 16px;
}

/* ── KPI strip discreto ──────────────────────────────────────── */
.kpi-strip {
    display: flex;
    align-items: stretch;
    gap: 0;
    margin-top: 18px;
}
.kpi-item {
    flex: 1;
    padding: 4px 20px;
    border-left: 1px solid var(--border-lo);
}
.kpi-item:first-child { border-left: none; padding-left: 2px; }
.kpi-item .kpi-label {
    font-family: 'Space Mono', monospace;
    font-size: 9.5px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted-dim);
    margin-bottom: 4px;
}
.kpi-item .kpi-value {
    font-family: 'Space Mono', monospace;
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--text);
}
.kpi-item .kpi-value.accent { color: var(--accent); }

/* ── Spatial insights ─────────────────────────────────────────── */
.insight-line {
    display: flex; align-items: baseline; gap: 10px;
    font-size: 13.5px; color: var(--muted);
    padding: 7px 0;
    border-bottom: 1px solid var(--border-lo);
}
.insight-line:last-child { border-bottom: none; }
.insight-line .dot-sm {
    width: 5px; height: 5px; border-radius: 50%;
    background: var(--accent); flex-shrink: 0;
}
.insight-line strong { color: var(--text); font-weight: 600; }

/* ── Rankings visuales ────────────────────────────────────────── */
.rank-item {
    display: grid;
    grid-template-columns: 30px 1fr 90px;
    align-items: center;
    gap: 12px;
    padding: 9px 0;
}
.rank-num {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: var(--muted-dim);
}
.rank-body .rank-name {
    font-size: 13px; color: var(--text); font-weight: 500;
    margin-bottom: 5px;
    display: flex; justify-content: space-between; gap: 10px;
}
.rank-body .rank-muni { color: var(--muted-dim); font-weight: 400; font-size: 11.5px; }
.rank-bar-track { height: 6px; background: var(--border-lo); border-radius: 3px; overflow: hidden; }
.rank-bar-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--accent), #8FB4FF); }
.rank-value {
    font-family: 'Space Mono', monospace;
    font-size: 12px; color: var(--text); text-align: right;
}

/* ── Exportaciones ────────────────────────────────────────────── */
.export-row { display: flex; gap: 10px; margin-top: 6px; }

/* ── AGEB Detail Panel ───────────────────────────────────────── */
.detail-panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
}
.detail-panel.empty {
    color: var(--muted-dim);
    font-size: 13px;
    text-align: center;
    padding: 26px 20px;
    border-style: dashed;
}
.detail-header {
    display: flex; align-items: baseline; justify-content: space-between;
    flex-wrap: wrap; gap: 6px;
    border-bottom: 1px solid var(--border-lo);
    padding-bottom: 10px; margin-bottom: 12px;
}
.detail-id {
    font-family: 'Space Mono', monospace;
    font-size: 15px; font-weight: 700; color: var(--text);
}
.detail-sub { font-size: 12px; color: var(--muted); }
.detail-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0;
}
.detail-stat { padding: 2px 16px; border-left: 1px solid var(--border-lo); }
.detail-stat:first-child { border-left: none; padding-left: 2px; }
.detail-stat-label {
    font-family: 'Space Mono', monospace;
    font-size: 9px; letter-spacing: 1.3px; text-transform: uppercase;
    color: var(--muted-dim); margin-bottom: 4px;
}
.detail-stat-value { font-family: 'Space Mono', monospace; font-size: 1rem; font-weight: 700; color: var(--text); }
.detail-stat-value.accent { color: var(--accent); }
.detail-badges { margin-top: 12px; }
.chip.warn { border-color: var(--warn); color: var(--warn); }

/* ── Ranking — fila seleccionable ────────────────────────────── */
.rank-row-wrap { display: flex; align-items: center; gap: 6px; }
.rank-row-wrap.selected .rank-item { background: var(--accent-soft); border-radius: 8px; padding-left: 8px; margin-left: -8px; }
.rank-row-wrap.selected .rank-name { color: var(--accent) !important; }
div[data-testid="stButton"].rank-select-btn > button,
.rank-select-col div[data-testid="stButton"] > button {
    background: transparent !important;
    border: 1px solid var(--border) !important;
    color: var(--muted) !important;
    padding: 4px 0 !important;
    min-height: 30px !important;
    font-size: 13px !important;
    width: 100%;
}
.rank-select-col div[data-testid="stButton"] > button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# HELPERS DE PRESENTACIÓN (sin lógica económica — solo formato)
# ══════════════════════════════════════════════════════════
def format_money(value: float) -> str:
    """Formatea un monto a $X.XX K/M/B MXN. Presentación pura, no transforma
    el valor subyacente producido por el motor."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000_000:
        return f"{sign}${v / 1_000_000_000:,.2f} B MXN"
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:,.2f} M MXN"
    if v >= 1_000:
        return f"{sign}${v / 1_000:,.2f} K MXN"
    return f"{sign}${v:,.2f} MXN"


def format_compact(value: float) -> str:
    """Formato compacto para KPIs/rankings (sin símbolo de moneda)."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000_000:
        return f"{sign}{v / 1_000_000_000:,.2f}B"
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:,.2f}M"
    if v >= 1_000:
        return f"{sign}{v / 1_000:,.2f}K"
    return f"{sign}{v:,.2f}"


def _municipio_code(cvegeo: str) -> str:
    """Extrae el código de municipio (posiciones 3-5) directamente del
    identificador cvegeo estándar INEGI. Solo parseo de string, sin
    lógica espacial ni económica."""
    cvegeo = str(cvegeo)
    return cvegeo[2:5] if len(cvegeo) >= 5 else "—"


def _md(html: str) -> None:
    """st.markdown envuelto con textwrap.dedent().strip().

    Streamlit interpreta bloques indentados con 4+ espacios como código
    Markdown (```) en vez de HTML crudo. Como los f-strings HTML de esta
    página viven dentro de funciones/loops indentados, sin dedent el HTML
    se renderiza como texto plano en vez de como interfaz. Este helper es
    puramente de presentación — no toca ningún dato ni columna del motor."""
    st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)


# Columnas de impacto ya producidas por el motor — solo se eligen para
# visualización, no se derivan valores nuevos.
_VARIABLE_OPTIONS = {
    "Propagated Impact": IMPACTO_PROPAGADO_COL,
    "Direct Impact": IMPACTO_DIRECTO_COL,
    "Indirect Impact": IMPACTO_INDIRECTO_COL,
}
_COLOR_OPTIONS = ["Blues", "Viridis", "Sunset", "Turbo", "Tealgrn"]
_BASEMAP_OPTIONS = {
    "Dark": "carto-darkmatter",
    "Light": "carto-positron",
    "Streets": "open-street-map",
}


# ══════════════════════════════════════════════════════════
# CARGA DEL MODELO (API pública existente — sin recálculo)
# ══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="Loading economic model…")
def cargar_modelo() -> ModeloEconomico:
    return ModeloEconomico(str(_REPO_ROOT / "serio" / "data"))

modelo = cargar_modelo()

_has_result = "simulation_report" in st.session_state and "simulation_gdf" in st.session_state

if "selected_ageb_id" not in st.session_state:
    st.session_state["selected_ageb_id"] = None

# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
status_label = "Ready" if not _has_result else "Result loaded"
st.markdown(
    f'<div class="pipeline-chip"><span class="dot"></span>'
    f'SERIO · Spatial Propagation · {status_label}</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="kicker">◆ SPATIAL SIMULATION</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Run Simulation</div>', unsafe_allow_html=True)
st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# TOOLBAR — definición de escenario (GIS command bar)
# ══════════════════════════════════════════════════════════
st.markdown('<div class="toolbar-wrap">', unsafe_allow_html=True)
t1, t2, t3, t4, t5 = st.columns([1.3, 1.7, 1.1, 1.1, 0.9])

with t1:
    nombres_estados = sorted(modelo.mapa_estados.keys())
    estado_nombre = st.selectbox("Region", nombres_estados, index=0)
    estado_key = modelo.mapa_estados[estado_nombre]

with t2:
    df_sec = modelo.df_sectores
    opciones_sector = [f"{r.scian} — {r.nombre}" for _, r in df_sec.iterrows()]
    sel_sector = st.selectbox("Economic Sector", opciones_sector, index=0)
    scian_sel = sel_sector.split(" — ")[0]
    sector_row = df_sec[df_sec["scian"].astype(str) == str(scian_sel)].iloc[0]
    sector_idx = int(sector_row["indice"])
    sector_name = sector_row["nombre"]

with t3:
    monto_pesos = st.number_input(
        "Shock (MXN)",
        value=100_000_000.0,
        min_value=-1e12,
        max_value=1e12,
        step=10_000_000.0,
        format="%.0f",
    )

with t4:
    rho = st.slider("ρ — Spatial Decay", 0.0, 0.95, 0.35, 0.01)

with t5:
    st.markdown('<div style="height:26px;"></div>', unsafe_allow_html=True)
    launch = st.button("▶ Launch", type="primary", use_container_width=True)

_md(f"""
<div class="chip-row">
    <span class="chip accent">📍 <b>Region</b>{estado_nombre}</span>
    <span class="chip accent">🏭 <b>Sector</b>{sector_name}</span>
    <span class="chip accent">💰 <b>Shock</b>{format_money(monto_pesos)}</span>
    <span class="chip accent">🌊 <b>ρ</b>{rho:.2f}</span>
</div>
""")
st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# MAPA — protagonista (render function)
# ══════════════════════════════════════════════════════════
def _prepare_map_data(gdf, value_col: str, sector_label: str):
    """Prepara columnas de presentación (share, municipio) sobre el
    GeoDataFrame ya producido por el motor. No recalcula economía."""
    gdf_map = gdf[gdf.geometry.notna()].copy()
    n_sin_geom = len(gdf) - len(gdf_map)

    total = gdf_map[value_col].sum()
    gdf_map["participacion_pct"] = (
        gdf_map[value_col] / total * 100 if total != 0 else 0.0
    )
    gdf_map["municipio"] = gdf_map[AGEB_ID_COL].map(_municipio_code)
    gdf_map["sector_shock"] = sector_label
    return gdf_map, n_sin_geom


def render_map_block(gdf, sector_label: str):
    """Bloque de mapa GIS: mini-toolbar (capa/variable/color/basemap),
    mapa grande, leyenda flotante y chip de fullscreen. Solo lectura sobre
    columnas del motor."""

    gdf_geo = gdf[gdf.geometry.notna()]
    if gdf_geo.empty:
        st.markdown(
            '<div class="map-placeholder">No spatial geometry available for this result.</div>',
            unsafe_allow_html=True,
        )
        return None, IMPACTO_PROPAGADO_COL

    st.markdown('<div class="map-toolbar">', unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns([1.3, 1, 1, 1.4, 1])
    with m1:
        st.markdown('<div class="layer-toggle-label">🗂 Layers</div>', unsafe_allow_html=True)
        layer_on = st.checkbox("AGEB Impact Layer", value=True, key="layer_toggle")
    with m2:
        var_label = st.selectbox("Variable", list(_VARIABLE_OPTIONS.keys()), index=0, key="var_sel")
        value_col = _VARIABLE_OPTIONS[var_label]
    with m3:
        color_label = st.selectbox("Color", _COLOR_OPTIONS, index=0, key="color_sel")
    with m4:
        basemap_label = st.selectbox("Basemap", list(_BASEMAP_OPTIONS.keys()), index=0, key="basemap_sel")
        basemap_style = _BASEMAP_OPTIONS[basemap_label]
    with m5:
        st.markdown('<div class="layer-toggle-label">Zoom / pan enabled</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    gdf_map, n_sin_geom = _prepare_map_data(gdf, value_col, sector_label)

    try:
        gdf_wgs84 = gdf_map.to_crs(epsg=4326)
    except Exception:
        gdf_wgs84 = gdf_map

    geojson = json.loads(gdf_wgs84.to_json())
    centroid = gdf_wgs84.geometry.unary_union.centroid

    color_kwargs = dict(color=value_col, color_continuous_scale=color_label) if layer_on else dict()

    fig = px.choropleth_mapbox(
        gdf_wgs84,
        geojson=geojson,
        locations=gdf_wgs84.index,
        mapbox_style=basemap_style,
        zoom=8,
        center={"lat": centroid.y, "lon": centroid.x},
        opacity=0.80 if layer_on else 0.35,
        **color_kwargs,
    )

    # Hover limpio y consistente, sin importar la variable elegida
    fig.update_traces(
        customdata=gdf_wgs84[[AGEB_ID_COL, "municipio", value_col, "participacion_pct"]].values,
        hovertemplate=(
            "<b>AGEB %{customdata[0]}</b><br>"
            "Municipio %{customdata[1]}<br>"
            f"{var_label}: " + "%{customdata[2]:,.2f}<br>"
            "Share: %{customdata[3]:.2f}%<extra></extra>"
        ),
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=680,
        paper_bgcolor="#0D1219",
        plot_bgcolor="#0D1219",
        font=dict(family="Inter", color="#F4F5F7", size=11),
        showlegend=False,
        hoverlabel=dict(
            bgcolor="#171F2C",
            bordercolor="#212B3B",
            font=dict(family="Inter", color="#F4F5F7", size=12),
        ),
        coloraxis_showscale=False,
    )

    # ── Highlight del AGEB seleccionado (map ↔ ranking ↔ detail panel,
    # mismo `session_state["selected_ageb_id"]`) — overlay puramente visual,
    # ninguna columna ni valor nuevo, solo resalta un punto ya existente. ──
    selected_id = st.session_state.get("selected_ageb_id")
    if selected_id is not None:
        sel_mask = gdf_wgs84[AGEB_ID_COL].astype(str) == str(selected_id)
        if sel_mask.any():
            sel_geom = gdf_wgs84.loc[sel_mask, "geometry"].iloc[0]
            sel_centroid = sel_geom.centroid
            fig.add_trace(go.Scattermapbox(
                lat=[sel_centroid.y], lon=[sel_centroid.x],
                mode="markers",
                marker=dict(size=26, color="rgba(244,245,247,0.0)"),
                hoverinfo="skip", showlegend=False,
            ))
            fig.add_trace(go.Scattermapbox(
                lat=[sel_centroid.y], lon=[sel_centroid.x],
                mode="markers",
                marker=dict(size=20, color="#F4F5F7", opacity=0.9),
                hoverinfo="skip", showlegend=False,
            ))
            fig.add_trace(go.Scattermapbox(
                lat=[sel_centroid.y], lon=[sel_centroid.x],
                mode="markers",
                marker=dict(size=12, color="#F5B942"),
                hoverinfo="skip", showlegend=False,
            ))

    st.markdown('<div class="map-card">', unsafe_allow_html=True)
    map_event = st.plotly_chart(
        fig,
        use_container_width=True,
        config={"scrollZoom": True, "displaylogo": False},
        on_select="rerun",
        selection_mode=("points",),
        key="spatial_map_chart",
    )

    # ── Selección por click — solo lectura de columnas ya existentes en
    # gdf_wgs84 (producidas por el motor). No se infiere ni recalcula nada.
    if map_event and map_event.get("selection", {}).get("point_indices"):
        idx_sel = map_event["selection"]["point_indices"][0]
        if 0 <= idx_sel < len(gdf_wgs84):
            new_id = str(gdf_wgs84.iloc[idx_sel][AGEB_ID_COL])
            if new_id != st.session_state.get("selected_ageb_id"):
                # `st.rerun()` evita el desfase de un rerun entre el click y
                # el highlight/panel de detalle/ranking — sin esto, el mapa
                # ya renderizado con la selección ANTERIOR se mostraría un
                # instante antes de reflejar el nuevo AGEB elegido.
                st.session_state["selected_ageb_id"] = new_id
                st.rerun()

    # ── Leyenda flotante + chip de fullscreen (overlay sobre el mapa) ──
    grad_css = {
        "Blues":   "linear-gradient(90deg,#0d2b52,#3b82f6,#bfdbfe)",
        "Viridis": "linear-gradient(90deg,#440154,#21908c,#fde725)",
        "Sunset":  "linear-gradient(90deg,#2c115f,#c1447e,#fddb92)",
        "Turbo":   "linear-gradient(90deg,#30123b,#29bf12,#f9c80e)",
        "Tealgrn": "linear-gradient(90deg,#0b3d3a,#1fa187,#c2f5e9)",
    }.get(color_label, "linear-gradient(90deg,#0d2b52,#3b82f6,#bfdbfe)")

    vmin = float(gdf_wgs84[value_col].min())
    vmax = float(gdf_wgs84[value_col].max())

    _md(f"""
    <div class="floating-legend-wrap" style="margin-top:-660px;">
      <div class="floating-legend">
        <div class="lg-title">Legend · {var_label}</div>
        <div class="legend-gradient" style="background:{grad_css};"></div>
        <div class="legend-scale-row"><span>{format_compact(vmin)}</span><span>{format_compact(vmax)}</span></div>
      </div>
    </div>
    <div class="fullscreen-chip" style="margin-top:-40px;">⛶ Fullscreen · scroll to zoom</div>
    """)

    st.markdown('</div>', unsafe_allow_html=True)

    if n_sin_geom > 0:
        st.caption(f"⚠ {n_sin_geom} AGEB(s) without geometry, excluded from the map.")

    return gdf_map, value_col


def render_detail_panel(gdf_map, value_col: str, var_label: str):
    """Panel de detalle del AGEB seleccionado (clic en el mapa o en el
    ranking, mismo `st.session_state["selected_ageb_id"]`). Solo lectura y
    formato sobre columnas ya producidas por el motor (IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL, es_isla) y sobre
    `participacion_pct`/`municipio` ya calculadas en `_prepare_map_data` —
    ninguna magnitud económica nueva se deriva aquí."""
    st.markdown(
        '<div class="section-label" style="display:flex; align-items:baseline; '
        'justify-content:space-between;">'
        '<span>AGEB Detail</span></div>',
        unsafe_allow_html=True,
    )

    selected_id = st.session_state.get("selected_ageb_id")

    if not selected_id:
        st.markdown(
            '<div class="detail-panel empty">Click an AGEB on the map, or select one from the '
            'ranking below, to inspect its detail.</div>',
            unsafe_allow_html=True,
        )
        return

    if gdf_map is None or gdf_map.empty:
        st.markdown(
            '<div class="detail-panel empty">No spatial result available to look up this AGEB.</div>',
            unsafe_allow_html=True,
        )
        return

    match = gdf_map[gdf_map[AGEB_ID_COL].astype(str) == str(selected_id)]
    if match.empty:
        st.markdown(
            f'<div class="detail-panel empty">AGEB <b>{selected_id}</b> is not present in the '
            'current result (it may lack geometry, or belong to a previous simulation).</div>',
            unsafe_allow_html=True,
        )
        return

    row = match.iloc[0]
    ranked = gdf_map.sort_values(value_col, ascending=False).reset_index(drop=True)
    rank_matches = ranked.index[ranked[AGEB_ID_COL].astype(str) == str(selected_id)]
    rank_pos = int(rank_matches[0]) + 1 if len(rank_matches) else None
    n_total = len(ranked)

    isla_badge = (
        '<span class="chip warn">⚠ Isolated AGEB — no spatial neighbors in the propagation graph</span>'
        if bool(row.get("es_isla", False)) else ""
    )
    rank_txt = f"Rank #{rank_pos} of {n_total} by {var_label}" if rank_pos else f"of {n_total} AGEBs"

    _md(f"""
    <div class="detail-panel">
        <div class="detail-header">
            <div class="detail-id">AGEB {row[AGEB_ID_COL]}</div>
            <div class="detail-sub">Municipio {row['municipio']} · {rank_txt}</div>
        </div>
        <div class="detail-stats">
            <div class="detail-stat">
                <div class="detail-stat-label">Direct Impact</div>
                <div class="detail-stat-value">{format_money(row[IMPACTO_DIRECTO_COL])}</div>
            </div>
            <div class="detail-stat">
                <div class="detail-stat-label">Indirect Impact</div>
                <div class="detail-stat-value">{format_money(row[IMPACTO_INDIRECTO_COL])}</div>
            </div>
            <div class="detail-stat">
                <div class="detail-stat-label">Propagated Impact</div>
                <div class="detail-stat-value accent">{format_money(row[IMPACTO_PROPAGADO_COL])}</div>
            </div>
            <div class="detail-stat">
                <div class="detail-stat-label">Share of Total ({var_label})</div>
                <div class="detail-stat-value">{row['participacion_pct']:.2f}%</div>
            </div>
        </div>
        {f'<div class="detail-badges">{isla_badge}</div>' if isla_badge else ''}
    </div>
    """)

    if st.button("✕ Clear selection", key="clear_selection_btn"):
        st.session_state["selected_ageb_id"] = None
        st.rerun()


# ══════════════════════════════════════════════════════════
# RENDER — resultado completo (jerarquía: summary → map → kpi → insights → rank → export)
# ══════════════════════════════════════════════════════════
def render_result(report, gdf, scenario: dict):
    sector_label = scenario.get("sector", "—")
    estado_label = scenario.get("estado", "—")
    rho_label = scenario.get("rho", 0.0)
    monto_label = scenario.get("monto_pesos", 0.0)

    mult_txt = (
        f"{report.multiplicador_global:.2f}×"
        if report.multiplicador_global is not None else "—"
    )

    # ── 1. Executive Summary (≤4 líneas) ─────────────────────────────
    _md(f"""
    <div class="exec-summary">
    A <strong>{format_money(monto_label)}</strong> shock in <strong>{sector_label}</strong>
    ({estado_label}) propagates to <strong>{format_money(report.shock_total_propagado)}</strong>
    in spatial economic impact — a <strong>{mult_txt}</strong> multiplier — across the AGEB
    network at ρ = {rho_label:.2f}, computed in {report.tiempo_ejecucion_seg:.2f}s.
    </div>
    """)

    # ── 2. Spatial Map ────────────────────────────────────────────────
    st.markdown('<div class="section-label">Spatial Map</div>', unsafe_allow_html=True)
    gdf_map, value_col = render_map_block(gdf, sector_label)
    var_label = [k for k, v in _VARIABLE_OPTIONS.items() if v == value_col][0]

    # ── 2b. AGEB Detail Panel (map ↔ ranking, mismo selected_ageb_id) ──
    render_detail_panel(gdf_map, value_col, var_label)

    # ── 3. KPIs (discretos) ───────────────────────────────────────────
    n_agebs = len(gdf)
    n_afectadas = int((gdf[IMPACTO_PROPAGADO_COL].abs() > 0).sum())
    impacto_promedio = float(gdf[IMPACTO_PROPAGADO_COL].mean()) if n_agebs else 0.0
    impacto_maximo = float(gdf[IMPACTO_PROPAGADO_COL].max()) if n_agebs else 0.0

    _md(f"""
    <div class="kpi-strip">
        <div class="kpi-item">
            <div class="kpi-label">Direct Impact</div>
            <div class="kpi-value">{format_money(report.shock_total_inicial)}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Spatial Impact</div>
            <div class="kpi-value accent">{format_money(report.shock_total_propagado)}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Multiplier</div>
            <div class="kpi-value">{mult_txt}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">AGEBs Affected</div>
            <div class="kpi-value">{n_afectadas:,} / {n_agebs:,}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Runtime</div>
            <div class="kpi-value">{report.tiempo_ejecucion_seg:.2f}s</div>
        </div>
    </div>
    """)

    # ── 4. Spatial Insights ───────────────────────────────────────────
    st.markdown('<div class="section-label">Spatial Insights</div>', unsafe_allow_html=True)

    if gdf_map is not None and not gdf_map.empty:
        top10_share = float(
            gdf_map.sort_values(value_col, ascending=False).head(10)["participacion_pct"].sum()
        )
        top_row = gdf_map.sort_values(value_col, ascending=False).iloc[0]
        n_municipios = gdf_map["municipio"].nunique()

        _md(f"""
        <div>
            <div class="insight-line"><span class="dot-sm"></span>
                Top 10 AGEBs concentrate <strong>{top10_share:.1f}%</strong> of total {var_label.lower()}.
            </div>
            <div class="insight-line"><span class="dot-sm"></span>
                Highest impact: AGEB <strong>{top_row[AGEB_ID_COL]}</strong>
                (municipio {top_row['municipio']}) with {format_money(top_row[value_col])}.
            </div>
            <div class="insight-line"><span class="dot-sm"></span>
                Effect spans <strong>{n_municipios}</strong> municipios across
                <strong>{n_afectadas:,}</strong> affected AGEBs.
            </div>
            <div class="insight-line"><span class="dot-sm"></span>
                Average impact per AGEB: <strong>{format_money(impacto_promedio)}</strong> ·
                Maximum: <strong>{format_money(impacto_maximo)}</strong>.
            </div>
        </div>
        """)
    else:
        st.caption("No geometry available to compute spatial insights.")

    # ── 5. Rankings (visual, no dataframe) ────────────────────────────
    st.markdown('<div class="section-label">Top 10 AGEBs</div>', unsafe_allow_html=True)

    if gdf_map is not None and not gdf_map.empty:
        df_rank = (
            gdf_map[[AGEB_ID_COL, "municipio", value_col]]
            .sort_values(value_col, ascending=False)
            .head(10)
            .reset_index(drop=True)
        )
        max_val = float(df_rank[value_col].abs().max()) or 1.0

        # NOTA: cada fila se arma como una sola línea, sin saltos ni
        # indentación. Un f-string HTML multilínea indentado dentro de un
        # loop es interpretado por Streamlit como bloque de código Markdown
        # (4+ espacios ⇒ ``` ) en vez de HTML, que es la causa del bug
        # reportado ("no renderiza, se ve el HTML crudo"). Concatenando en
        # una sola línea se evita el problema de raíz — sin tocar ningún
        # valor del motor.
        #
        # Cada fila vive en dos columnas: el HTML existente (barra + valor)
        # a la izquierda, y un botón real de Streamlit a la derecha que
        # asigna `selected_ageb_id` — mismo estado que ya consume el mapa
        # (highlight) y el panel de detalle, cerrando el loop de selección
        # mapa ↔ ranking ↔ detalle.
        selected_id = st.session_state.get("selected_ageb_id")
        for i, row in df_rank.iterrows():
            pct = min(100.0, abs(float(row[value_col])) / max_val * 100)
            row_id = str(row[AGEB_ID_COL])
            is_selected = row_id == str(selected_id) if selected_id else False
            row_html = (
                '<div class="rank-item">'
                f'<div class="rank-num">#{i + 1:02d}</div>'
                '<div class="rank-body">'
                '<div class="rank-name"><span>AGEB '
                f'{row[AGEB_ID_COL]} '
                f'<span class="rank-muni">· municipio {row["municipio"]}</span></span></div>'
                '<div class="rank-bar-track">'
                f'<div class="rank-bar-fill" style="width:{pct:.1f}%;"></div>'
                '</div>'
                '</div>'
                f'<div class="rank-value">{format_compact(row[value_col])}</div>'
                '</div>'
            )
            wrap_class = "rank-row-wrap selected" if is_selected else "rank-row-wrap"

            col_row, col_btn = st.columns([0.92, 0.08])
            with col_row:
                st.markdown(f'<div class="{wrap_class}">{row_html}</div>', unsafe_allow_html=True)
            with col_btn:
                st.markdown('<div class="rank-select-col">', unsafe_allow_html=True)
                if st.button(
                    "◉" if is_selected else "○",
                    key=f"rank_select_{row_id}",
                    help=f"Select AGEB {row_id} on the map",
                ):
                    st.session_state["selected_ageb_id"] = row_id
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.caption("No geometry available to build the ranking.")

    # ── 6. Export ──────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Export</div>', unsafe_allow_html=True)
    e1, e2, e3 = st.columns(3)

    with e1:
        try:
            geojson_bytes = gdf.to_json().encode("utf-8")
            st.download_button(
                "⬇ GeoJSON", data=geojson_bytes,
                file_name="lattise_simulation_result.geojson",
                mime="application/geo+json", use_container_width=True,
            )
        except Exception as e:
            st.button("⬇ GeoJSON", disabled=True, use_container_width=True)
            st.caption(f"Unavailable: {e}")

    with e2:
        try:
            buf = io.BytesIO()
            gdf.to_parquet(buf)
            st.download_button(
                "⬇ Parquet", data=buf.getvalue(),
                file_name="lattise_simulation_result.parquet",
                mime="application/octet-stream", use_container_width=True,
            )
        except Exception as e:
            st.button("⬇ Parquet", disabled=True, use_container_width=True)
            st.caption(f"Unavailable: {e}")

    with e3:
        report_json = json.dumps(report.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
        st.download_button(
            "⬇ JSON Report", data=report_json,
            file_name="lattise_simulation_report.json",
            mime="application/json", use_container_width=True,
        )


def render_empty_state():
    _md("""
    <div class="exec-summary">
    Define a scenario in the toolbar above and press <strong>Launch</strong> to run the
    spatial propagation engine. Results — map, KPIs, insights, rankings and exports —
    will appear here once the simulation completes.
    </div>
    """)
    st.markdown('<div class="section-label">Spatial Map</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="map-placeholder">Spatial visualization will appear here once a '
        'simulation has been executed.</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════
# EJECUCIÓN — API pública existente, sin recálculo de etapas
# ══════════════════════════════════════════════════════════
if launch:
    st.session_state["selected_ageb_id"] = None
    with st.spinner("Running simulation…"):
        try:
            resultado_simulacion = modelo.simular(estado_key, sector_idx, monto_pesos)
            gdf_final, report = run_simulation_engine(resultado_simulacion, rho)

            st.session_state["simulation_scenario"] = {
                "estado": estado_nombre,
                "estado_key": estado_key,
                "sector": sector_name,
                "sector_idx": sector_idx,
                "monto_pesos": monto_pesos,
                "rho": rho,
            }
            st.session_state["simulation_gdf"] = gdf_final
            st.session_state["simulation_report"] = report
            st.session_state["simulation_timestamp"] = time.time()

        except Exception as e:
            st.error(f"Simulation failed: {e}")
        else:
            render_result(report, gdf_final, st.session_state["simulation_scenario"])
elif _has_result:
    render_result(
        st.session_state["simulation_report"],
        st.session_state["simulation_gdf"],
        st.session_state.get("simulation_scenario", {}),
    )
else:
    render_empty_state()