# app/Home.py
"""
Lattise Studio — Home
Consola de acceso a los módulos de la plataforma. No contiene lógica
económica ni referencias al motor interno — solo navegación.
"""
import streamlit as st

st.set_page_config(
    page_title="Lattise Studio",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════
# CSS GLOBAL — consola operativa (Bloomberg Terminal / Palantir Gotham)
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

:root {
    --bg:        #05070C;
    --panel:     #0B0F17;
    --panel-hi:  #121826;
    --border:    #1C2434;
    --border-hi: #2A3448;
    --text:      #E8EAEE;
    --muted:     #7C8598;
    --muted-dim: #4C5568;
    --accent:    #4E86F5;
    --accent-dim: #2C4A87;
    --ok:        #2FBF83;
    --warn:      #E0A93E;
    --mono:      'Space Mono', monospace;
    --sans:      'Inter', sans-serif;
}

html, body, .stApp { background: var(--bg) !important; }
* { font-family: var(--sans); }

header {visibility: hidden;}
[data-testid="stToolbar"]     {display: none;}
[data-testid="stDecoration"]  {display: none;}
[data-testid="stStatusWidget"]{display: none;}
footer {visibility: hidden;}
#MainMenu {visibility: hidden;}

.block-container {
    max-width: 1240px;
    padding-top: 1.6rem;
    padding-bottom: 2rem;
}

/* ── Botones Streamlit reestilizados — rectos, sin gradientes ────── */
div[data-testid="stButton"] > button {
    border-radius: 4px;
    font-weight: 600;
    font-size: 13.5px;
    font-family: var(--sans);
    padding: 9px 18px;
    transition: all 0.12s ease;
    border: 1px solid var(--border-hi);
    letter-spacing: 0.2px;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: var(--accent);
    border: 1px solid var(--accent);
    color: #05070C;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #6A9BF9;
    border-color: #6A9BF9;
}
div[data-testid="stButton"] > button[kind="secondary"] {
    background: transparent;
    color: var(--text);
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    border-color: var(--muted);
    color: var(--text);
    background: var(--panel-hi);
}

/* ── Tipografía utilitaria ─────────────────────────────────────── */
.kicker {
    font-family: var(--mono); font-size: 11px; letter-spacing: 3px;
    text-transform: uppercase; color: var(--accent); margin-bottom: 14px;
}
.section-label {
    font-family: var(--mono); font-size: 10.5px; letter-spacing: 3px;
    text-transform: uppercase; color: var(--muted-dim); margin-bottom: 8px;
}
.section-title {
    font-size: 1.55rem; font-weight: 700; color: var(--text);
    margin: 0 0 6px 0; letter-spacing: -0.4px;
}
.section-sub {
    color: var(--muted); font-size: 13.5px; max-width: 640px;
    margin: 0 0 28px 0; line-height: 1.6;
}

/* ── Status bar superior (metadata técnica, estilo terminal) ─────── */
.statusbar {
    display: flex; align-items: center; justify-content: space-between;
    border: 1px solid var(--border); border-radius: 6px;
    background: var(--panel); padding: 9px 16px; margin-bottom: 28px;
    font-family: var(--mono); font-size: 10.5px; letter-spacing: 1px;
    color: var(--muted); flex-wrap: wrap; gap: 8px;
}
.statusbar .dot-ok {
    display: inline-block; width: 6px; height: 6px; border-radius: 50%;
    background: var(--ok); margin-right: 7px; box-shadow: 0 0 6px var(--ok);
}
.statusbar .divider-v { color: var(--border-hi); }

/* ── Hero ─────────────────────────────────────────────────────── */
.hero { padding: 8px 0 8px 0; }
.hero-title {
    font-size: 3.1rem; font-weight: 800; letter-spacing: -1.8px;
    line-height: 1.03; margin: 0; color: var(--text);
}
.hero-sub {
    color: var(--muted); font-size: 15px; max-width: 620px;
    margin: 18px 0 0 0; line-height: 1.65; font-weight: 400;
}

/* ── Módulos (grid de navegación primaria) ───────────────────────── */
.mod-card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 20px 22px; height: 100%;
    display: flex; flex-direction: column; gap: 10px;
    transition: border-color 0.12s ease;
}
.mod-card:hover { border-color: var(--border-hi); }
.mod-head { display: flex; align-items: center; justify-content: space-between; }
.mod-index {
    font-family: var(--mono); font-size: 11px; color: var(--muted-dim); letter-spacing: 1px;
}
.mod-badge {
    font-family: var(--mono); font-size: 9.5px; letter-spacing: 1.5px;
    text-transform: uppercase; padding: 2px 8px; border-radius: 3px;
    border: 1px solid var(--border-hi); color: var(--muted);
}
.mod-badge.core { color: var(--ok); border-color: rgba(47,191,131,0.35); background: rgba(47,191,131,0.06); }
.mod-badge.new  { color: var(--accent); border-color: rgba(78,134,245,0.4); background: rgba(78,134,245,0.08); }
.mod-title { font-size: 1.02rem; font-weight: 700; color: var(--text); letter-spacing: -0.2px; }
.mod-desc { color: var(--muted); font-size: 12.5px; line-height: 1.55; flex-grow: 1; }
.mod-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
.mod-tag {
    font-family: var(--mono); font-size: 9.5px; color: var(--muted);
    border: 1px solid var(--border); border-radius: 3px; padding: 2px 7px;
}

/* ── Tags de casos de uso (chips monoespaciados) ─────────────────── */
.tag-strip { display: flex; flex-wrap: wrap; gap: 8px; }
.usecase-tag {
    font-family: var(--mono); font-size: 11.5px; color: var(--text);
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 4px; padding: 8px 14px; letter-spacing: 0.3px;
}

/* ── Especificaciones de plataforma (lista técnica densa) ─────────── */
.spec-row {
    display: flex; gap: 16px; padding: 14px 0;
    border-top: 1px solid var(--border);
}
.spec-row:last-child { border-bottom: 1px solid var(--border); }
.spec-code {
    font-family: var(--mono); font-size: 11px; color: var(--accent);
    width: 34px; flex-shrink: 0; padding-top: 2px;
}
.spec-title { color: var(--text); font-weight: 600; font-size: 14px; margin-bottom: 3px; }
.spec-desc { color: var(--muted); font-size: 12.5px; line-height: 1.55; max-width: 620px; }

/* ── Divider ──────────────────────────────────────────────────── */
.divider { border: none; border-top: 1px solid var(--border); margin: 44px 0 40px 0; }

/* ── Footer ───────────────────────────────────────────────────── */
.footer { padding: 28px 0 6px 0; border-top: 1px solid var(--border); }
.footer-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.footer-title { color: var(--text); font-weight: 700; font-size: 13.5px; letter-spacing: -0.1px; }
.footer-sub { color: var(--muted-dim); font-size: 11.5px; margin-top: 2px; }
.footer-powered {
    color: var(--muted-dim); font-size: 10.5px; font-family: var(--mono);
    letter-spacing: 1px; text-align: right;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# STATUS BAR
# ══════════════════════════════════════════════════════════
st.markdown("""
<div class="statusbar">
  <div><span class="dot-ok"></span>SYSTEM OPERATIONAL</div>
  <div class="divider-v">·</div>
  <div>32 ESTADOS</div>
  <div class="divider-v">·</div>
  <div>78 SECTORES SCIAN</div>
  <div class="divider-v">·</div>
  <div>BASE INEGI 2018</div>
  <div class="divider-v">·</div>
  <div>MOTOR FLQ + RAS · LEONTIEF REGIONALIZADO</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# HERO
# ══════════════════════════════════════════════════════════
st.markdown("""
<div class="hero">
  <div class="kicker">◆ SPATIAL ECONOMIC INTELLIGENCE</div>
  <div class="hero-title">Lattise Studio</div>
  <div class="hero-sub">
    Infraestructura de análisis para simular, mapear y explorar el impacto
    económico territorial a nivel AGEB, utilizando datos oficiales y un
    motor de insumo-producto regionalizado.
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# MÓDULOS — navegación primaria hacia las 4 páginas del producto
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Módulos</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Plataforma</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">Cuatro módulos, una sola fuente de verdad: '
    'el motor geoespacial-económico de Lattise.</div>',
    unsafe_allow_html=True,
)

MODULES = [
    {
        "index": "01",
        "badge": "core", "badge_label": "Simulación",
        "title": "Launch Workspace",
        "desc": "Ejecuta un shock de demanda final en un AGEB y sector específico "
                "y observa su propagación espacial sobre el territorio.",
        "tags": ["Shock de demanda", "Propagación espacial", "AGEB"],
        "page": "pages/1_Run Simulation.py",
    },
    {
        "index": "02",
        "badge": "core", "badge_label": "Resultados",
        "title": "View Results",
        "desc": "Consulta y compara los resultados de simulaciones ya ejecutadas, "
                "con detalle por AGEB y por sector.",
        "tags": ["Detalle por AGEB", "Comparación", "Export"],
        "page": "pages/2_View Results.py",
    },
    {
        "index": "03",
        "badge": "core", "badge_label": "Estructura",
        "title": "Spatial Cluster Intelligence",
        "desc": "Comunidades económicas detectadas por Louvain sobre la red "
                "productiva nacional, regional y de contagio financiero.",
        "tags": ["Louvain", "Comunidades económicas", "Contagio"],
        "page": "pages/4_Spatial_Cluster_Intelligence.py",
    },
    {
        "index": "04",
        "badge": "new", "badge_label": "Nuevo",
        "title": "Opportunity Explorer",
        "desc": "Explora el territorio ya simulado: perfil económico por AGEB, "
                "comunidad, municipio y relaciones espaciales — sin recalcular nada.",
        "tags": ["Perfil territorial", "Búsqueda", "Insights"],
        "page": "pages/5_Opportunity_Explorer.py",
    },
]

mod_cols = st.columns(4)
for col, mod in zip(mod_cols, MODULES):
    with col:
        tags_html = "".join(f'<span class="mod-tag">{t}</span>' for t in mod["tags"])
        st.markdown(f"""
        <div class="mod-card">
          <div class="mod-head">
            <span class="mod-index">{mod['index']}</span>
            <span class="mod-badge {mod['badge']}">{mod['badge_label']}</span>
          </div>
          <div class="mod-title">{mod['title']}</div>
          <div class="mod-desc">{mod['desc']}</div>
          <div class="mod-tags">{tags_html}</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
        if st.button("Abrir →", key=f"mod_{mod['index']}", use_container_width=True):
            st.switch_page(mod["page"])
        st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# USE CASES
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Aplicaciones</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Casos de uso</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">Diseñado para decisiones que dependen de '
    'dónde ocurre el impacto, no solo de cuánto.</div>',
    unsafe_allow_html=True,
)

use_cases = [
    "Nearshoring", "Inversión industrial", "Cadenas de suministro",
    "Proyectos de infraestructura", "Política económica regional",
    "Desarrollo territorial", "Banca de desarrollo", "Estudios de pre-factibilidad",
]
tags_html = "".join(f'<span class="usecase-tag">{uc}</span>' for uc in use_cases)
st.markdown(f'<div class="tag-strip">{tags_html}</div>', unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# PLATFORM CAPABILITIES — lista técnica densa
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-label">Plataforma</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Capacidades</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-sub">Todo lo necesario para pasar de un escenario '
    'a una decisión informada.</div>',
    unsafe_allow_html=True,
)

capabilities = [
    ("01", "Simulación de shocks", "Ejecuta escenarios de demanda final sobre la matriz Leontief regionalizada (FLQ + RAS), con resultados a nivel AGEB."),
    ("02", "Propagación espacial", "Observa cómo se distribuye un impacto económico a través del territorio mediante el operador de propagación espacial."),
    ("03", "Comunidades económicas", "Identifica qué sectores y AGEBs conforman comunidades económicas cohesivas, detectadas vía Louvain sobre la red productiva."),
    ("04", "Exploración territorial", "Perfil de cualquier AGEB, comunidad o municipio — sin ejecutar una nueva simulación — vía Opportunity Explorer."),
    ("05", "Comparación de escenarios", "Compara distintos supuestos y magnitudes de shock para evaluar alternativas de política o inversión."),
    ("06", "Export de resultados", "Descarga resultados en CSV, JSON, GeoJSON o PNG, listos para integrarse a reportes y sistemas externos."),
]
for code, title, desc in capabilities:
    st.markdown(f"""
    <div class="spec-row">
      <div class="spec-code">{code}</div>
      <div>
        <div class="spec-title">{title}</div>
        <div class="spec-desc">{desc}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# CTA FINAL
# ══════════════════════════════════════════════════════════
cta_l, cta_r = st.columns([2.2, 1])
with cta_l:
    st.markdown('<div class="section-title" style="margin-bottom:4px;">¿Listo para ver dónde aterriza tu impacto?</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub" style="margin-bottom:0;">Ejecuta tu primera simulación en menos de un minuto, o explora el territorio ya simulado.</div>', unsafe_allow_html=True)
with cta_r:
    if st.button("Start Simulation →", type="primary", use_container_width=True, key="cta_bottom"):
        st.switch_page("pages/1_Run Simulation.py")
    if st.button("Opportunity Explorer →", type="secondary", use_container_width=True, key="cta_explorer"):
        st.switch_page("pages/5_Opportunity_Explorer.py")

# ══════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════
st.markdown(f"""
<div class="footer">
  <div class="footer-row">
    <div>
      <div class="footer-title">Lattise Studio</div>
      <div class="footer-sub">Spatial Economic Intelligence Platform</div>
    </div>
    <div class="footer-powered">POWERED BY THE LATTISE GEOSPATIAL ENGINE</div>
  </div>
</div>
""", unsafe_allow_html=True)