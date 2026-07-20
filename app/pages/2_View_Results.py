# app/pages/2_View_Results.py
"""
Lattise Studio — View Results
Consume exclusivamente lo que la página Run Simulation ya guardó en
st.session_state (GeoDataFrame + SimulationReport, producidos por
spatial.simulation.engine.run_simulation_engine()). No recalcula nada,
no contiene lógica económica ni espacial propia.
"""
import io
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ── Resolución de rutas del repo (app/pages/ → app/ → repo root) ───────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spatial.config import AGEB_ID_COL
from spatial.simulation.engine import (
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
)

st.set_page_config(
    page_title="View Results — Lattise Studio",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════
# CSS — mismo lenguaje visual que Home.py / Run Simulation
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

:root {
    --bg:        #0B0F17;
    --panel:     #131A26;
    --panel-hi:  #1A2333;
    --border:    #232C3D;
    --text:      #F4F5F7;
    --muted:     #8A93A6;
    --muted-dim: #5C6478;
    --accent:    #5B8DEF;
    --accent-soft: rgba(91,141,239,0.12);
    --ok:        #34D399;
    --warn:      #F87171;
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
    max-width: 1240px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

.kicker {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 10px;
}
.page-title {
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: -1px;
    color: var(--text);
    margin: 0 0 6px 0;
}
.page-sub {
    color: var(--muted);
    font-size: 14.5px;
    margin-bottom: 8px;
}
.panel-title {
    color: var(--text);
    font-weight: 700;
    font-size: 17px;
    margin: 0 0 14px 0;
    letter-spacing: -0.3px;
}
.section-label {
    font-family: 'Space Mono', monospace;
    font-size: 10.5px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: var(--muted-dim);
    margin: 30px 0 14px 0;
}

.card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 22px;
}
.map-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px 18px 6px 18px;
}
.empty-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 90px 30px;
    text-align: center;
}
.empty-title {
    color: var(--text);
    font-weight: 700;
    font-size: 18px;
    margin-bottom: 8px;
}
.empty-sub {
    color: var(--muted);
    font-size: 14px;
    max-width: 420px;
    margin: 0 auto;
    line-height: 1.6;
}

[data-testid="stMetric"] {
    background: var(--panel-hi) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 16px 18px !important;
}
[data-testid="stMetricLabel"] {
    color: var(--muted) !important;
    font-size: 11px !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
}
[data-testid="stMetricValue"] {
    color: var(--text) !important;
    font-family: 'Space Mono', monospace !important;
}

div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button {
    border-radius: 10px;
    font-weight: 600;
    font-size: 14px;
    padding: 10px 18px;
    border: 1px solid var(--border);
    background: var(--panel-hi);
    color: var(--text);
    transition: all 0.15s ease;
}
div[data-testid="stButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover {
    border-color: var(--accent);
    color: var(--accent);
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
}

hr.thin { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
st.markdown('<div class="kicker">◆ RESULTS</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Simulation Results</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-sub">Impacto territorial propagado de la simulación '
    'más reciente.</div>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# ESTADO — sin simulación previa
# ══════════════════════════════════════════════════════════
gdf = st.session_state.get("simulation_gdf")
report = st.session_state.get("simulation_report")
scenario = st.session_state.get("simulation_scenario", {})

if gdf is None or report is None:
    st.markdown("""
    <div class="empty-card">
        <div class="empty-title">No results to display yet</div>
        <div class="empty-sub">
            Run a simulation first to explore its spatial and economic impact here.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div style="height:18px;"></div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([2, 1.2, 2])
    with mid:
        if st.button("Go to Run Simulation", type="primary", use_container_width=True):
            st.switch_page("pages/1_Run_Simulation.py")
    st.stop()

# ══════════════════════════════════════════════════════════
# LAYOUT — DOS COLUMNAS
# ══════════════════════════════════════════════════════════
col_map, col_side = st.columns([1.4, 1], gap="large")

# ── COLUMNA IZQUIERDA — MAPA ─────────────────────────────────
with col_map:
    st.markdown('<div class="panel-title">Spatial Impact Map</div>', unsafe_allow_html=True)

    gdf_map = gdf[gdf.geometry.notna()].copy()
    n_sin_geom = len(gdf) - len(gdf_map)

    if gdf_map.empty:
        st.markdown("""
        <div class="empty-card">
            <div class="empty-title">No spatial geometry available</div>
            <div class="empty-sub">
                The simulation completed, but no AGEB in the result carries geometry.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        try:
            gdf_wgs84 = gdf_map.to_crs(epsg=4326)
        except Exception:
            gdf_wgs84 = gdf_map

        geojson = json.loads(gdf_wgs84.to_json())
        centroid = gdf_wgs84.geometry.union_all().centroid

        fig = px.choropleth_mapbox(
            gdf_wgs84,
            geojson=geojson,
            locations=gdf_wgs84.index,
            color=IMPACTO_PROPAGADO_COL,
            color_continuous_scale="Blues",
            mapbox_style="carto-darkmatter",
            zoom=8,
            center={"lat": centroid.y, "lon": centroid.x},
            opacity=0.75,
            hover_name=AGEB_ID_COL,
            hover_data={
                IMPACTO_PROPAGADO_COL: ":.2f",
                IMPACTO_DIRECTO_COL: ":.2f",
                IMPACTO_INDIRECTO_COL: ":.2f",
            },
            labels={
                IMPACTO_PROPAGADO_COL: "Propagated impact",
                IMPACTO_DIRECTO_COL: "Direct impact",
                IMPACTO_INDIRECTO_COL: "Indirect impact",
            },
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=560,
            paper_bgcolor="#131A26",
            font=dict(family="Inter", color="#F4F5F7", size=11),
            coloraxis_colorbar=dict(
                title="Propagated<br>impact",
                tickfont=dict(color="#8A93A6"),
                title_font=dict(color="#8A93A6"),
            ),
        )
        st.markdown('<div class="map-card">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
        st.markdown('</div>', unsafe_allow_html=True)

        if n_sin_geom > 0:
            st.caption(f"⚠ {n_sin_geom} AGEB(s) sin geometría, excluida(s) del mapa.")

# ── COLUMNA DERECHA — KPIs + TOP 10 ──────────────────────────
with col_side:
    st.markdown('<div class="panel-title">Key Metrics</div>', unsafe_allow_html=True)

    k1, k2 = st.columns(2)
    k1.metric("Direct Economic Impact", f"{report.shock_total_inicial:,.2f}")
    k2.metric("Spatial Economic Impact", f"{report.shock_total_propagado:,.2f}")

    k3, k4 = st.columns(2)
    mult_txt = (
        f"{report.multiplicador_global:.4f}"
        if report.multiplicador_global is not None else "—"
    )
    k3.metric("Spatial Multiplier", mult_txt)
    k4.metric("Execution Time", f"{report.tiempo_ejecucion_seg:.3f} s")

    st.markdown('<div class="section-label">Top 10 AGEBs by Impact</div>', unsafe_allow_html=True)

    df_top = gdf.drop(columns="geometry", errors="ignore").copy()
    df_top["_abs_impacto"] = df_top[IMPACTO_PROPAGADO_COL].abs()
    df_top = (
        df_top.sort_values("_abs_impacto", ascending=False)
        .drop(columns="_abs_impacto")
        .head(10)
        .reset_index(drop=True)
    )

    df_display = df_top[[
        AGEB_ID_COL, IMPACTO_DIRECTO_COL, IMPACTO_PROPAGADO_COL, IMPACTO_INDIRECTO_COL,
    ]].rename(columns={
        AGEB_ID_COL: "AGEB",
        IMPACTO_DIRECTO_COL: "Direct",
        IMPACTO_PROPAGADO_COL: "Propagated",
        IMPACTO_INDIRECTO_COL: "Indirect",
    })

    st.dataframe(
        df_display.style.format({
            "Direct": "{:,.2f}",
            "Propagated": "{:,.2f}",
            "Indirect": "{:,.2f}",
        }).background_gradient(cmap="Blues", subset=["Propagated"]),
        use_container_width=True,
        height=340,
        hide_index=True,
    )

# ══════════════════════════════════════════════════════════
# DESCARGAS
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Export Results</div>', unsafe_allow_html=True)

dl1, dl2, dl3 = st.columns(3)

with dl1:
    try:
        geojson_bytes = gdf.to_json().encode("utf-8")
        st.download_button(
            "⬇ Download GeoJSON",
            data=geojson_bytes,
            file_name="lattise_simulation_result.geojson",
            mime="application/geo+json",
            use_container_width=True,
        )
    except Exception as e:
        st.button("⬇ Download GeoJSON", disabled=True, use_container_width=True)
        st.caption(f"GeoJSON export unavailable: {e}")

with dl2:
    try:
        buf = io.BytesIO()
        gdf.to_parquet(buf)
        st.download_button(
            "⬇ Download Parquet",
            data=buf.getvalue(),
            file_name="lattise_simulation_result.parquet",
            mime="application/octet-stream",
            use_container_width=True,
        )
    except Exception as e:
        st.button("⬇ Download Parquet", disabled=True, use_container_width=True)
        st.caption(f"Parquet export unavailable: {e}")

with dl3:
    report_json = json.dumps(report.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
    st.download_button(
        "⬇ Download JSON Report",
        data=report_json,
        file_name="lattise_simulation_report.json",
        mime="application/json",
        use_container_width=True,
    )