# app/pages/5_Opportunity_Explorer.py
"""
Lattise Studio — Opportunity Explorer

Herramienta de exploración territorial de oportunidades económicas.
NO es un dashboard, NO es un mapa aislado, NO es otra versión de Run
Simulation: es una capa de lectura sobre datos que YA existen.

Fuentes de datos — solo lectura de artefactos ya congelados:
    1. data/analytics/sector_cluster.json  (Louvain, offline, congelado)
    2. spatial.config.WAREHOUSE_PARQUET    (Stage 5, CERRADO)
    3. st.session_state["simulation_gdf"/"simulation_report"]
       (Stage 8C, producido por Run Simulation — OPCIONAL)
    4. spatial.simulation.SpatialMatrix (Stage 8A, CERRADO — AGEBs vecinas)

Ninguna magnitud económica nueva se calcula en esta página. Toda la
aritmética (comunidad/sector dominante, participación, disolución
municipal, agregación de shock) reside en `app.helpers.aggregation` y
replica exactamente los criterios ya establecidos en
`app/pages/4_Spatial_Cluster_Intelligence.py`. No se agrega Opportunity
Score, no se inventan métricas nuevas.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.components import map_view, search_sidebar  # noqa: E402
from app.components.styles import inject_styles  # noqa: E402
from app.helpers import export_utils  # noqa: E402
from app.helpers.aggregation import (  # noqa: E402
    aggregate_shock_by,
    build_ageb_universe,
    build_community_summary,
    build_municipality_gdf,
    build_municipality_summary,
)
from app.helpers.data_sources import (  # noqa: E402
    AGEB_ID_COL,
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
    SECTOR_CLUSTER_JSON,
    WAREHOUSE_PARQUET,
    get_simulation_gdf,
    load_cluster_artifact,
    load_sector_names,
    load_warehouse_gdf,
)
from app.panels import (  # noqa: E402
    community_profile,
    insights_panel,
    opportunity_profile,
    relationships_panel,
    statistics_panel,
    territorial_context,
)

st.set_page_config(
    page_title="Opportunity Explorer — Lattise Studio",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_styles()

# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
st.markdown('<div class="kicker">◎ OPPORTUNITY EXPLORER</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Explorador de Oportunidades Territoriales</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Qué caracteriza cada territorio, a qué comunidad económica pertenece y '
    'cómo se conecta dentro del sistema — usando exclusivamente información ya calculada.</div>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# CARGA — artefactos congelados, solo lectura
# ══════════════════════════════════════════════════════════
artifact = load_cluster_artifact()
if artifact is None:
    st.markdown(f"""
    <div class="empty-state">
      <div style="font-size:1.1rem; font-weight:700; color:var(--text); margin-bottom:8px;">
        No se encontró el artefacto de comunidades económicas
      </div>
      <div>Corre: <code>python -m scripts.build_sector_clusters</code></div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

warehouse_gdf = load_warehouse_gdf()
if warehouse_gdf is None:
    st.markdown(f"""
    <div class="empty-state">
      <div style="font-size:1.1rem; font-weight:700; color:var(--text); margin-bottom:8px;">
        Warehouse espacial no disponible
      </div>
      <div>No se encontró <code>{Path(WAREHOUSE_PARQUET).relative_to(_REPO_ROOT)}</code> (Stage 5).</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

sector_names = load_sector_names()

ageb_gdf, long_cluster_df, long_sector_df, integrity_report = build_ageb_universe(
    warehouse_gdf, artifact, sector_names
)
if ageb_gdf.empty:
    st.error("Ningún AGEB del warehouse tiene un sector mapeado a una comunidad.")
    st.stop()

community_summary = build_community_summary(ageb_gdf, artifact)
muni_gdf, _muni_cluster_weights = build_municipality_gdf(ageb_gdf, long_cluster_df)

sim_gdf = get_simulation_gdf()
shock_activo = sim_gdf is not None

shock_by_muni, shock_cov_muni = (None, {})
if shock_activo:
    shock_by_muni, shock_cov_muni = aggregate_shock_by(
        sim_gdf, ageb_gdf[[AGEB_ID_COL, "municipio"]], "municipio"
    )
muni_summary = build_municipality_summary(muni_gdf, community_summary, shock_by_muni)

# Fusiona el impacto propagado directamente en ageb_gdf (sin recalcular
# nada — es la misma columna ya producida por Run Simulation) para que
# la capa "Simulation Impact" del mapa pueda leerla como cualquier otra
# columna existente.
if shock_activo:
    sim_cols = [AGEB_ID_COL, IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL]
    ageb_gdf = ageb_gdf.merge(
        pd.DataFrame(sim_gdf[sim_cols]), on=AGEB_ID_COL, how="left"
    )
    ageb_gdf[IMPACTO_PROPAGADO_COL] = ageb_gdf[IMPACTO_PROPAGADO_COL].fillna(0.0)

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

ageb_df = pd.DataFrame(ageb_gdf.drop(columns="geometry"))

# ══════════════════════════════════════════════════════════
# CONTEXTO COMPARTIDO — misma fuente de verdad para Search, Map y Tabs
# ══════════════════════════════════════════════════════════
ctx = SimpleNamespace(
    ageb_gdf=ageb_gdf, ageb_gdf_wgs84=ageb_gdf_wgs84, ageb_df=ageb_df,
    muni_gdf=muni_gdf, muni_gdf_wgs84=muni_gdf_wgs84, muni_summary=muni_summary,
    community_summary=community_summary,
    color_by_cluster=color_by_cluster, nombre_by_cluster=nombre_by_cluster,
    sim_gdf=sim_gdf, shock_activo=shock_activo,
    dimmed_ids=set(),
)

# ══════════════════════════════════════════════════════════
# LAYOUT — Search/Filters/Explorer · Mapa
# ══════════════════════════════════════════════════════════
col_side, col_map = st.columns([1.05, 2.95])

with col_side:
    search_sidebar.render_search_and_filters(ctx)
    filtered_ageb_df = search_sidebar.apply_filters(ctx.ageb_df)
    ctx.dimmed_ids = set(ctx.ageb_df[AGEB_ID_COL]) - set(filtered_ageb_df[AGEB_ID_COL])
    search_sidebar.render_explorer_list(ctx, filtered_ageb_df)

with col_map:
    if shock_activo:
        st.markdown('<div class="insight-card shock" style="margin-bottom:8px;">◆ Simulación cargada — capa "Simulation Impact" disponible</div>',
                     unsafe_allow_html=True)
    map_view.render_map(ctx)

# ══════════════════════════════════════════════════════════
# TABS — Opportunity Profile · Community · Territory · Statistics ·
#         Insights · Relationships
# ══════════════════════════════════════════════════════════
selected_ageb = st.session_state.get("oe_selected_ageb")

tab_profile, tab_community, tab_territory, tab_stats, tab_insights, tab_relationships = st.tabs([
    "Opportunity Profile", "Community", "Territory", "Statistics", "Insights", "Relationships",
])

with tab_profile:
    opportunity_profile.render(ctx, selected_ageb)
with tab_community:
    community_profile.render(ctx, selected_ageb)
with tab_territory:
    territorial_context.render(ctx, selected_ageb)
with tab_stats:
    statistics_panel.render(ctx)
with tab_insights:
    insights_panel.render(ctx, selected_ageb)
with tab_relationships:
    relationships_panel.render(ctx, selected_ageb)

# ══════════════════════════════════════════════════════════
# EXPORT — reutiliza Stage 9 (spatial.visualization.maps) para
# PNG/GeoJSON; CSV/JSON son serialización directa de las tablas ya
# construidas.
# ══════════════════════════════════════════════════════════
with st.expander("⬇ Export"):
    ec1, ec2, ec3, ec4 = st.columns(4)

    with ec1:
        geojson_source = ageb_gdf[ageb_gdf[AGEB_ID_COL].isin(filtered_ageb_df[AGEB_ID_COL])]
        st.download_button(
            "GeoJSON (AGEB filtrados)",
            export_utils.geojson_bytes(geojson_source, id_col=AGEB_ID_COL),
            "opportunity_explorer_agebs.geojson", "application/geo+json",
            use_container_width=True,
        )
    with ec2:
        try:
            png_source = ageb_gdf[ageb_gdf[AGEB_ID_COL].isin(filtered_ageb_df[AGEB_ID_COL])]
            png_bytes = export_utils.choropleth_png_bytes(
                png_source, "peso_total_ageb", id_col=AGEB_ID_COL,
                title="Peso económico territorial — Opportunity Explorer",
                legend_label="Peso económico",
            )
            st.download_button(
                "Mapa PNG (peso económico)", png_bytes,
                "opportunity_explorer_map.png", "image/png", use_container_width=True,
            )
        except Exception as exc:  # nunca truena el resto de la página por un export
            st.caption(f"PNG no disponible: {exc}")
    with ec3:
        st.download_button(
            "CSV (AGEB filtrados)",
            export_utils.csv_bytes(filtered_ageb_df),
            "opportunity_explorer_agebs.csv", "text/csv", use_container_width=True,
        )
    with ec4:
        payload = filtered_ageb_df
        if selected_ageb is not None:
            sel_row = ageb_df[ageb_df[AGEB_ID_COL] == selected_ageb]
            if not sel_row.empty:
                payload = sel_row
        st.download_button(
            "JSON (perfil / selección)",
            export_utils.json_bytes(payload),
            "opportunity_explorer_profile.json", "application/json", use_container_width=True,
        )

# ══════════════════════════════════════════════════════════
# TRAZABILIDAD E INTEGRIDAD DE DATOS
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
            f"Cobertura shock↔municipio: {shock_cov_muni.get('n_agebs_con_grupo_y_shock', 0)} AGEB · "
            f"sin municipio: {shock_cov_muni.get('n_agebs_shock_sin_grupo', 0)}."
        )
    st.caption(
        "Opportunity Explorer no recalcula Warehouse, Spatial Graph, Louvain ni ninguna simulación — "
        "solo lee y presenta artefactos ya cerrados del motor. No se calcula ningún Opportunity Score "
        "ni índice compuesto nuevo en esta página."
    )
