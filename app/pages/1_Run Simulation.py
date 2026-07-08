# app/pages/1_Run Simulation.py
"""
Lattise Studio — Run Simulation
Orquesta exclusivamente las APIs públicas ya cerradas del motor:
    serio.loader.ModeloEconomico.simular()
    spatial.simulation.engine.run_simulation_engine()
No recalcula Warehouse, Graph, SEE ni SERIO. No contiene lógica económica.
"""
import sys
import time
from pathlib import Path

import streamlit as st

# ── Resolución de rutas del repo (app/pages/ → app/ → repo root) ───────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from serio.loader import ModeloEconomico
from spatial.simulation.engine import run_simulation_engine

st.set_page_config(
    page_title="Run Simulation — Lattise Studio",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════
# CSS — mismo lenguaje visual que Home.py
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
    max-width: 1180px;
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
    font-size: 18px;
    margin: 0 0 18px 0;
    letter-spacing: -0.3px;
}
.section-label {
    font-family: 'Space Mono', monospace;
    font-size: 10.5px;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: var(--muted-dim);
    margin: 28px 0 14px 0;
}

/* ── Widgets ──────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stNumberInput"] > div > div {
    background: var(--panel-hi) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text) !important;
}
[data-testid="stSelectbox"] label,
[data-testid="stNumberInput"] label,
[data-testid="stSlider"] label {
    color: var(--muted) !important;
    font-size: 13px !important;
    font-weight: 500 !important;
}
[data-testid="stSlider"] div[data-baseweb="slider"] > div > div {
    background: var(--accent) !important;
}

div[data-testid="stButton"] > button {
    border-radius: 10px;
    font-weight: 600;
    font-size: 15px;
    padding: 12px 22px;
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

/* ── Tarjetas ─────────────────────────────────────────────── */
.card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 26px 24px;
}
.preview-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 26px 24px;
    min-height: 460px;
    display: flex;
    flex-direction: column;
}
.preview-empty {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: var(--muted-dim);
    font-size: 14px;
}
.map-placeholder {
    margin-top: 18px;
    border: 1px dashed var(--border);
    border-radius: 12px;
    padding: 60px 20px;
    text-align: center;
    color: var(--muted-dim);
    font-size: 13px;
    background: rgba(255,255,255,0.015);
}

.summary-row {
    display: flex;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13.5px;
}
.summary-row:last-child { border-bottom: none; }
.summary-label { color: var(--muted); }
.summary-value { color: var(--text); font-weight: 600; }

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

hr.thin { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
st.markdown('<div class="kicker">◆ NEW SIMULATION</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Run Simulation</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-sub">Define un escenario económico y ejecuta el motor '
    'de simulación espacial.</div>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# CARGA DEL MODELO (API pública existente — sin recálculo)
# ══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="Cargando modelo económico…")
def cargar_modelo() -> ModeloEconomico:
    return ModeloEconomico(str(_REPO_ROOT / "serio" / "data"))

modelo = cargar_modelo()

# ══════════════════════════════════════════════════════════
# LAYOUT — DOS COLUMNAS
# ══════════════════════════════════════════════════════════
col_left, col_right = st.columns([1, 1.15], gap="large")

# ── COLUMNA IZQUIERDA — CONTROL PANEL ───────────────────────
with col_left:
    st.markdown('<div class="panel-title">New Simulation</div>', unsafe_allow_html=True)

    nombres_estados = sorted(modelo.mapa_estados.keys())
    estado_nombre = st.selectbox("Region", nombres_estados, index=0)
    estado_key = modelo.mapa_estados[estado_nombre]

    df_sec = modelo.df_sectores
    opciones_sector = [f"{r.scian} — {r.nombre}" for _, r in df_sec.iterrows()]
    sel_sector = st.selectbox("Economic Sector", opciones_sector, index=0)
    scian_sel = sel_sector.split(" — ")[0]
    sector_row = df_sec[df_sec["scian"].astype(str) == str(scian_sel)].iloc[0]
    sector_idx = int(sector_row["indice"])
    sector_name = sector_row["nombre"]

    monto_pesos = st.number_input(
        "Shock Amount (MXN)",
        value=100_000_000.0,
        min_value=-1e12,
        max_value=1e12,
        step=10_000_000.0,
        format="%.0f",
    )

    rho = st.slider("ρ — Spatial Decay Parameter", 0.0, 0.95, 0.35, 0.01)

    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
    launch = st.button("Launch Simulation", type="primary", use_container_width=True)

    st.markdown('<div class="section-label">Scenario Summary</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="card">
        <div class="summary-row"><span class="summary-label">Region</span><span class="summary-value">{estado_nombre}</span></div>
        <div class="summary-row"><span class="summary-label">Sector</span><span class="summary-value">{sector_name}</span></div>
        <div class="summary-row"><span class="summary-label">Shock Amount</span><span class="summary-value">${monto_pesos:,.0f} MXN</span></div>
        <div class="summary-row"><span class="summary-label">ρ</span><span class="summary-value">{rho:.2f}</span></div>
    </div>
    """, unsafe_allow_html=True)

# ── COLUMNA DERECHA — SIMULATION PREVIEW ────────────────────
with col_right:
    preview_slot = st.container()

def render_preview_empty():
    with preview_slot:
        st.markdown("""
        <div class="preview-card">
            <div class="panel-title">Simulation Preview</div>
            <div class="preview-empty">No simulation has been executed yet.</div>
            <div class="map-placeholder">Spatial visualization will appear here.</div>
        </div>
        """, unsafe_allow_html=True)

def render_preview_result(report):
    with preview_slot:
        st.markdown('<div class="panel-title">Simulation Preview</div>', unsafe_allow_html=True)
        st.success("Simulation completed successfully.")

        m1, m2 = st.columns(2)
        m1.metric("Shock Inicial", f"{report.shock_total_inicial:,.2f}")
        m2.metric("Shock Propagado", f"{report.shock_total_propagado:,.2f}")

        m3, m4 = st.columns(2)
        mult_txt = (
            f"{report.multiplicador_global:.4f}"
            if report.multiplicador_global is not None else "—"
        )
        m3.metric("Multiplicador Espacial", mult_txt)
        m4.metric("Tiempo de Ejecución", f"{report.tiempo_ejecucion_seg:.3f} s")

        st.markdown(
            '<div class="map-placeholder">Spatial visualization will appear here.</div>',
            unsafe_allow_html=True,
        )

# ══════════════════════════════════════════════════════════
# EJECUCIÓN — API pública existente, sin recálculo de etapas
# ══════════════════════════════════════════════════════════
if launch:
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
            with preview_slot:
                st.markdown('<div class="panel-title">Simulation Preview</div>', unsafe_allow_html=True)
                st.error(f"Simulation failed: {e}")
        else:
            render_preview_result(report)
elif "simulation_report" in st.session_state:
    render_preview_result(st.session_state["simulation_report"])
else:
    render_preview_empty()