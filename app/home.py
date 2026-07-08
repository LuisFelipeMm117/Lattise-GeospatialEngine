# app/Home.py
"""
Lattise Studio — Home
Landing page del producto. No contiene lógica económica ni referencias
al motor interno. Solo orquesta navegación hacia las páginas del MVP.
"""
import streamlit as st

st.set_page_config(
    page_title="Lattise Studio",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════
# CSS GLOBAL
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

:root {
    --bg:        #0B0F17;
    --bg-alt:    #10151F;
    --panel:     #131A26;
    --panel-hi:  #1A2333;
    --border:    #232C3D;
    --text:      #F4F5F7;
    --muted:     #8A93A6;
    --muted-dim: #5C6478;
    --accent:    #5B8DEF;
    --accent-soft: rgba(91,141,239,0.12);
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
    padding-bottom: 2rem;
}

/* ── Botones Streamlit reestilizados ─────────────────────── */
div[data-testid="stButton"] > button {
    border-radius: 10px;
    font-weight: 600;
    font-size: 15px;
    padding: 10px 22px;
    transition: all 0.15s ease;
    border: 1px solid var(--border);
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: var(--accent);
    border: 1px solid var(--accent);
    color: white;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #4A78D6;
    border-color: #4A78D6;
}
div[data-testid="stButton"] > button[kind="secondary"] {
    background: transparent;
    color: var(--text);
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    border-color: var(--muted);
    color: var(--text);
}

/* ── Tipografía utilitaria ────────────────────────────────── */
.kicker {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 18px;
}
.section-label {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--muted-dim);
    text-align: center;
    margin-bottom: 10px;
}
.section-title {
    font-size: 2rem;
    font-weight: 700;
    color: var(--text);
    text-align: center;
    margin: 0 0 12px 0;
    letter-spacing: -0.5px;
}
.section-sub {
    color: var(--muted);
    text-align: center;
    font-size: 15px;
    max-width: 560px;
    margin: 0 auto 48px auto;
    line-height: 1.6;
}

/* ── Hero ─────────────────────────────────────────────────── */
.hero {
    padding: 64px 0 40px 0;
    text-align: center;
}
.hero-title {
    font-size: 4.2rem;
    font-weight: 800;
    letter-spacing: -2.5px;
    line-height: 1.02;
    margin: 0;
    background: linear-gradient(180deg, #FFFFFF 0%, #AEB8CC 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero-sub {
    color: var(--muted);
    font-size: 1.15rem;
    max-width: 620px;
    margin: 26px auto 0 auto;
    line-height: 1.65;
    font-weight: 400;
}

/* ── Flow (How it works) ─────────────────────────────────── */
.flow-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
    max-width: 420px;
    margin: 0 auto;
}
.flow-step {
    width: 100%;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 22px;
    display: flex;
    align-items: center;
    gap: 14px;
}
.flow-num {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: var(--accent);
    background: var(--accent-soft);
    border-radius: 6px;
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.flow-text {
    color: var(--text);
    font-size: 15px;
    font-weight: 500;
}
.flow-arrow {
    color: var(--muted-dim);
    font-size: 18px;
    padding: 6px 0;
}

/* ── Tarjetas genéricas ───────────────────────────────────── */
.card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 26px 24px;
    height: 100%;
    transition: border-color 0.15s ease, transform 0.15s ease;
}
.card:hover {
    border-color: #34405A;
    transform: translateY(-2px);
}
.card-icon {
    font-size: 26px;
    margin-bottom: 14px;
    display: block;
}
.card-title {
    color: var(--text);
    font-weight: 600;
    font-size: 16px;
    margin-bottom: 6px;
}
.card-desc {
    color: var(--muted);
    font-size: 13.5px;
    line-height: 1.55;
}

.usecase-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    height: 100%;
}
.usecase-title {
    color: var(--text);
    font-weight: 600;
    font-size: 14.5px;
}

/* ── Divider ──────────────────────────────────────────────── */
.divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 72px 0 56px 0;
}

/* ── Footer ───────────────────────────────────────────────── */
.footer {
    text-align: center;
    padding: 40px 0 10px 0;
}
.footer-title {
    color: var(--text);
    font-weight: 700;
    font-size: 15px;
    letter-spacing: -0.2px;
}
.footer-sub {
    color: var(--muted);
    font-size: 13px;
    margin-top: 4px;
}
.footer-powered {
    color: var(--muted-dim);
    font-size: 12px;
    margin-top: 14px;
    font-family: 'Space Mono', monospace;
    letter-spacing: 0.5px;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# HERO
# ══════════════════════════════════════════════════════════
st.markdown("""
<div class="hero">
  <div class="kicker" style="text-align:center;">◆ SPATIAL ECONOMIC INTELLIGENCE</div>
  <div class="hero-title">Lattise Studio</div>
  <div class="hero-sub">
    Una plataforma para simular el impacto espacial de cambios económicos
    utilizando datos oficiales y modelos econométricos.
  </div>
</div>
""", unsafe_allow_html=True)

_, c1, c2, _ = st.columns([3, 1.3, 1.3, 3])
with c1:
    if st.button("Start Simulation", type="primary", use_container_width=True):
        st.switch_page("pages/1_Run Simulation.py")
with c2:
    if st.button("Learn More", type="secondary", use_container_width=True):
        st.switch_page("pages/3_About.py")

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# HOW IT WORKS
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Process</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">How it works</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">De una pregunta económica a un mapa de impacto '
    'territorial, en cinco pasos.</div>',
    unsafe_allow_html=True,
)

flow_steps = [
    "Select Region",
    "Choose Economic Sector",
    "Define Scenario",
    "Run Simulation",
    "Explore Spatial Results",
]
flow_html = '<div class="flow-wrap">'
for i, step in enumerate(flow_steps, start=1):
    flow_html += f"""
    <div class="flow-step">
        <div class="flow-num">{i}</div>
        <div class="flow-text">{step}</div>
    </div>
    """
    if i < len(flow_steps):
        flow_html += '<div class="flow-arrow">↓</div>'
flow_html += '</div>'
st.markdown(flow_html, unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# USE CASES
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Applications</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Use Cases</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">Diseñado para las decisiones que dependen de '
    'dónde ocurre el impacto, no solo de cuánto.</div>',
    unsafe_allow_html=True,
)

use_cases = [
    "Nearshoring",
    "Industrial Investment",
    "Supply Chains",
    "Infrastructure Projects",
    "Economic Policy",
    "Regional Development",
]
uc_cols = st.columns(3)
for i, uc in enumerate(use_cases):
    with uc_cols[i % 3]:
        st.markdown(
            f'<div class="usecase-card"><div class="usecase-title">{uc}</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# PLATFORM CAPABILITIES
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Platform</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Platform Capabilities</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">Todo lo necesario para pasar de un escenario '
    'a una decisión informada.</div>',
    unsafe_allow_html=True,
)

capabilities = [
    ("🗺️", "Spatial Analysis", "Visualiza cómo se distribuye el impacto económico a través del territorio."),
    ("📊", "Economic Simulation", "Ejecuta escenarios de shock sobre datos oficiales con resultados inmediatos."),
    ("🏭", "Sector Impact", "Identifica qué sectores absorben y transmiten el impacto de un cambio económico."),
    ("📈", "Scenario Comparison", "Compara distintos supuestos y magnitudes para evaluar alternativas."),
    ("💾", "Export Results", "Descarga tus resultados en los formatos que tu equipo ya utiliza."),
    ("🌎", "Interactive Maps", "Explora el resultado espacial de cada simulación de forma interactiva."),
]
cap_cols = st.columns(3)
for i, (icon, title, desc) in enumerate(capabilities):
    with cap_cols[i % 3]:
        st.markdown(f"""
        <div class="card">
            <span class="card-icon">{icon}</span>
            <div class="card-title">{title}</div>
            <div class="card-desc">{desc}</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# CTA FINAL
# ══════════════════════════════════════════════════════════
st.markdown("""
<div style="text-align:center; padding: 0 0 8px 0;">
  <div class="section-title" style="font-size:1.7rem;">Ready to see where your impact lands?</div>
  <div class="section-sub" style="margin-bottom:32px;">
    Comienza tu primera simulación en menos de un minuto.
  </div>
</div>
""", unsafe_allow_html=True)

_, cta_col, _ = st.columns([3, 1.6, 3])
with cta_col:
    if st.button("Start Simulation →", type="primary", use_container_width=True, key="cta_bottom"):
        st.switch_page("pages/1_Run Simulation.py")

# ══════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════
st.markdown("""
<div class="footer">
  <div class="footer-title">Lattise Studio</div>
  <div class="footer-sub">Spatial Economic Intelligence Platform</div>
  <div class="footer-powered">POWERED BY THE LATTISE GEOSPATIAL ENGINE</div>
</div>
""", unsafe_allow_html=True)
