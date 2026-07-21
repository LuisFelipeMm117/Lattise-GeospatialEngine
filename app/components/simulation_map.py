# app/components/simulation_map.py
"""
Run Simulation -- mapa GIS (protagonista de la pagina).

Extraido de app/pages/1_Run_Simulation.py sin cambios de comportamiento.
Todo lo agregado en el sprint UX/UI original es presentacion pura sobre
columnas ya producidas por el motor (IMPACTO_DIRECTO_COL,
IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL, geometry). No se
recalcula, reinterpreta ni agrega ninguna magnitud economica nueva. Los
selectores de "variable", "color" y "basemap" unicamente cambian como
se visualizan columnas existentes.
"""
from __future__ import annotations

import json

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from spatial.config import AGEB_ID_COL
from spatial.simulation.engine import (
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
)

from app.helpers.formatting import md, municipio_code
from app.helpers.simulation_formatting import format_compact, format_money

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


def _prepare_map_data(gdf, value_col: str, sector_label: str):
    """Prepara columnas de presentación (share, municipio) sobre el
    GeoDataFrame ya producido por el motor. No recalcula economía."""
    gdf_map = gdf[gdf.geometry.notna()].copy()
    n_sin_geom = len(gdf) - len(gdf_map)

    total = gdf_map[value_col].sum()
    gdf_map["participacion_pct"] = (
        gdf_map[value_col] / total * 100 if total != 0 else 0.0
    )
    gdf_map["municipio"] = gdf_map[AGEB_ID_COL].map(municipio_code)
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
    centroid = gdf_wgs84.geometry.union_all().centroid

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

    md(f"""
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

    md(f"""
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

