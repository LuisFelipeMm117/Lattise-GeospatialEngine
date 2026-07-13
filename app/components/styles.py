# app/components/styles.py
"""
Opportunity Explorer — hoja de estilos.

Mismos design tokens (paleta, tipografía, radios) que
`app/pages/1_Run Simulation.py` y `app/pages/4_Spatial_Cluster_Intelligence.py`
para que las tres páginas de Lattise Studio se sientan como una sola
aplicación GIS profesional (ArcGIS Pro / CARTO / Palantir Foundry).
"""
from __future__ import annotations

import streamlit as st


def inject_styles() -> None:
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
    .block-container { max-width: 1560px; padding-top: 1.2rem; padding-bottom: 2.5rem; }

    .kicker {
        font-family: 'Space Mono', monospace; font-size: 11px; letter-spacing: 3px;
        text-transform: uppercase; color: var(--accent);
    }
    .page-title { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.8px; color: var(--text); margin: 2px 0 10px 0; }
    .subtitle { color: var(--muted); font-size: 13.5px; margin-bottom: 14px; }

    .oe-card {
        background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
        padding: 10px 12px; margin-bottom: 7px;
    }
    .oe-card.active { border-color: var(--accent); background: var(--panel-hi); }
    .oe-card.dim { opacity: 0.4; }
    .oe-card-head { display: flex; align-items: center; gap: 8px; }
    .oe-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
    .oe-card-name { font-size: 12.5px; font-weight: 600; color: var(--text); line-height: 1.25; }
    .oe-card-meta { font-family: 'Space Mono', monospace; font-size: 10.5px; color: var(--muted); margin-top: 4px; padding-left: 18px; }

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

    .empty-state {
        background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
        padding: 40px; text-align: center; color: var(--muted);
    }
    .empty-state code { color: var(--accent); }

    .relationship-chain { display: flex; flex-direction: column; gap: 2px; margin: 8px 0; }
    .relationship-node {
        background: var(--panel-hi); border: 1px solid var(--border); border-radius: 8px;
        padding: 8px 12px; font-size: 12.5px; color: var(--text);
    }
    .relationship-node .rn-label { font-family: 'Space Mono', monospace; font-size: 9px;
        letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted); display: block; margin-bottom: 2px; }
    .relationship-arrow { text-align: center; color: var(--muted-dim); font-size: 13px; margin: 0; }

    hr.thin { border: none; border-top: 1px solid var(--border); margin: 6px 0 16px 0; }
    </style>
    """, unsafe_allow_html=True)
