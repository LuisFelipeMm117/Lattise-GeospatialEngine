# app/components/simulation_styles.py
"""
Run Simulation -- estilos CSS (lenguaje visual GIS profesional).

Extraido de app/pages/1_Run_Simulation.py sin modificar una sola linea
de CSS -- mismo bloque exacto, solo envuelto en una funcion para que
la pagina deje de ser un monolito de 1,451 lineas. Presentacion pura,
cero logica de negocio.
"""
from __future__ import annotations

import streamlit as st


def inject_simulation_styles() -> None:
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
    .rank-bar-fill.negative { background: linear-gradient(90deg, #DC2626, #F87171); }
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
    
    /* ── Scenario Manager (Fase 2) ───────────────────────────────── */
    .scenario-manager-wrap { margin: 2px 0 18px 0; }
    .scenario-chip {
        display: flex; align-items: center; gap: 9px;
        background: var(--panel-hi);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 22px;
        margin-bottom: 6px;
        overflow: hidden;
    }
    .scenario-chip.active { border-color: var(--accent); background: var(--accent-soft); }
    .scenario-chip .sc-dot { color: var(--accent); font-size: 9px; flex-shrink: 0; }
    .scenario-chip.active .sc-dot { color: var(--ok); }
    .scenario-chip .sc-text {
        font-family: 'Space Mono', monospace; font-size: 11.5px;
        color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .scenario-chip.active .sc-text { color: var(--text); }
    .scenario-manager-empty {
        font-size: 12.5px; color: var(--muted-dim); padding: 4px 0 14px 0;
    }
    </style>
    """, unsafe_allow_html=True)
