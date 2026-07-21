# app/panels/simulation_comparison.py
"""
Run Simulation -- vista de comparacion (Fase 3).

Extraido de app/pages/1_Run_Simulation.py sin cambios de comportamiento.
No recalcula economia: solo lee report/gdf de las entradas de historial
seleccionadas y muestra deltas de presentacion entre ambas.
"""
from __future__ import annotations

import json

import plotly.express as px
import streamlit as st

from spatial.config import AGEB_ID_COL
from spatial.simulation.engine import IMPACTO_PROPAGADO_COL

from app.components.simulation_map import _prepare_map_data
from app.helpers.formatting import md
from app.helpers.simulation_formatting import format_compact, format_money

def render_compare_map(gdf, sector_label: str, key_suffix: str):
    """Mapa estático (sin toolbar interactiva) para el modo Comparación.
    Misma preparación de datos que render_map_block (_prepare_map_data),
    fija variable=Propagated Impact para que ambos lados sean comparables.
    Solo lectura sobre columnas ya producidas por el motor."""
    gdf_geo = gdf[gdf.geometry.notna()]
    if gdf_geo.empty:
        st.markdown(
            '<div class="map-placeholder">No spatial geometry available for this result.</div>',
            unsafe_allow_html=True,
        )
        return

    value_col = IMPACTO_PROPAGADO_COL
    gdf_map, n_sin_geom = _prepare_map_data(gdf, value_col, sector_label)
    try:
        gdf_wgs84 = gdf_map.to_crs(epsg=4326)
    except Exception:
        gdf_wgs84 = gdf_map

    geojson = json.loads(gdf_wgs84.to_json())
    centroid = gdf_wgs84.geometry.union_all().centroid

    fig = px.choropleth_mapbox(
        gdf_wgs84, geojson=geojson, locations=gdf_wgs84.index,
        mapbox_style="carto-darkmatter", zoom=6.5,
        center={"lat": centroid.y, "lon": centroid.x},
        opacity=0.80, color=value_col, color_continuous_scale="Blues",
    )
    fig.update_traces(
        customdata=gdf_wgs84[[AGEB_ID_COL, "municipio", value_col]].values,
        hovertemplate=(
            "<b>AGEB %{customdata[0]}</b><br>Municipio %{customdata[1]}<br>"
            "Propagated Impact: %{customdata[2]:,.2f}<extra></extra>"
        ),
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), height=420,
        paper_bgcolor="#0D1219", plot_bgcolor="#0D1219",
        font=dict(family="Inter", color="#F4F5F7", size=10),
        showlegend=False, coloraxis_showscale=False,
    )
    st.plotly_chart(
        fig, use_container_width=True,
        config={"scrollZoom": False, "displaylogo": False},
        key=f"cmp_map_{key_suffix}",
    )
    if n_sin_geom > 0:
        st.caption(f"⚠ {n_sin_geom} AGEB(s) without geometry, excluded.")


def compare_side(entry: dict) -> None:
    """Columna de comparación: resumen + KPIs + mapa estático de una
    entrada de historial. Presentación pura sobre report/gdf ya calculados."""
    scenario = entry["scenario"]
    report = entry["report"]
    gdf = entry["gdf"]
    sector_label = scenario.get("sector", "—")

    md(f"""
    <div class="scenario-chip active" style="margin-bottom:10px;">
        <span class="sc-text">{entry['label']}</span>
    </div>
    """)

    mult_txt = (
        f"{report.multiplicador_global:.2f}×"
        if report.multiplicador_global is not None else "—"
    )
    n_agebs = len(gdf)
    n_afectadas = int((gdf[IMPACTO_PROPAGADO_COL].abs() > 0).sum())

    md(f"""
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
    </div>
    """)

    render_compare_map(gdf, sector_label, key_suffix=entry["id"])


def render_compare_view(entry_a: dict, entry_b: dict) -> None:
    """Vista lado a lado de dos escenarios ya calculados (Fase 3). No
    recalcula economía: solo lee report/gdf de las entradas de historial
    seleccionadas y muestra deltas de presentación entre ambas."""
    c_title, c_back = st.columns([0.85, 0.15])
    with c_title:
        st.markdown('<div class="section-label">Scenario Comparison</div>', unsafe_allow_html=True)
    with c_back:
        if st.button("← Back", key="btn_close_compare", use_container_width=True):
            st.session_state["compare_mode"] = False
            st.rerun()

    col_a, col_b = st.columns(2)
    with col_a:
        compare_side(entry_a)
    with col_b:
        compare_side(entry_b)

    # ── Delta summary — siempre calculable, sin importar si los dos
    # escenarios comparten estado/sector (aritmética sobre report, no
    # sobre columnas espaciales). ──────────────────────────────────
    report_a, report_b = entry_a["report"], entry_b["report"]
    d_spatial = report_b.shock_total_propagado - report_a.shock_total_propagado
    mult_a = report_a.multiplicador_global or 0.0
    mult_b = report_b.multiplicador_global or 0.0
    d_mult = mult_b - mult_a
    n_af_a = int((entry_a["gdf"][IMPACTO_PROPAGADO_COL].abs() > 0).sum())
    n_af_b = int((entry_b["gdf"][IMPACTO_PROPAGADO_COL].abs() > 0).sum())

    st.markdown('<div class="section-label">Delta (B − A)</div>', unsafe_allow_html=True)
    md(f"""
    <div class="kpi-strip">
        <div class="kpi-item">
            <div class="kpi-label">Δ Spatial Impact</div>
            <div class="kpi-value accent">{format_money(d_spatial)}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Δ Multiplier</div>
            <div class="kpi-value">{d_mult:+.2f}×</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Δ AGEBs Affected</div>
            <div class="kpi-value">{n_af_b - n_af_a:+,}</div>
        </div>
    </div>
    """)

    # ── Top divergencia por AGEB — solo cuando ambos escenarios viven en
    # el mismo estado (misma malla de AGEBs), condición explícita, no
    # inferida. ───────────────────────────────────────────────────────
    same_state = entry_a["scenario"].get("estado_key") == entry_b["scenario"].get("estado_key")
    if same_state:
        st.markdown('<div class="section-label">Top Divergent AGEBs</div>', unsafe_allow_html=True)
        ga = entry_a["gdf"][[AGEB_ID_COL, IMPACTO_PROPAGADO_COL]].rename(
            columns={IMPACTO_PROPAGADO_COL: "impacto_a"})
        gb = entry_b["gdf"][[AGEB_ID_COL, IMPACTO_PROPAGADO_COL]].rename(
            columns={IMPACTO_PROPAGADO_COL: "impacto_b"})
        merged = ga.merge(gb, on=AGEB_ID_COL, how="inner")
        merged["diff"] = merged["impacto_b"] - merged["impacto_a"]
        top_div = merged.reindex(merged["diff"].abs().sort_values(ascending=False).index).head(10)
        if top_div.empty:
            st.caption("No overlapping AGEBs to compare.")
        else:
            max_val = float(top_div["diff"].abs().max()) or 1.0
            for _, row in top_div.iterrows():
                pct = min(100.0, abs(float(row["diff"])) / max_val * 100)
                sign_class = "" if row["diff"] >= 0 else "negative"
                row_html = (
                    '<div class="rank-item">'
                    f'<div class="rank-body"><div class="rank-name"><span>AGEB {row[AGEB_ID_COL]}</span></div>'
                    '<div class="rank-bar-track">'
                    f'<div class="rank-bar-fill {sign_class}" style="width:{pct:.1f}%;"></div>'
                    '</div></div>'
                    f'<div class="rank-value">{format_compact(row["diff"])}</div>'
                    '</div>'
                )
                st.markdown(f'<div class="rank-row-wrap">{row_html}</div>', unsafe_allow_html=True)
    else:
        st.caption(
            "Scenarios belong to different states — per-AGEB divergence is not "
            "comparable across disjoint spatial grids. Showing aggregate deltas only."
        )
