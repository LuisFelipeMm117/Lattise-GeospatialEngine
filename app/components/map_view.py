# app/components/map_view.py
"""
Opportunity Explorer — Capa 2 (Mapa).

Reutiliza el `GeoDataFrame` ya construido por `app.helpers.aggregation`
(`ageb_gdf` / `muni_gdf`). No recalcula nada — solo agrega capas
visuales (Choroplethmapbox) sobre columnas ya existentes, con el mismo
criterio de "un trace por categoría" que ya usa
`app/pages/4_Spatial_Cluster_Intelligence.py` (`CommunityLayer`,
`MunicipalityLayer`) para que la leyenda categórica sea legible.

Capas disponibles (todas sobre columnas ya calculadas):
    Economic Community  — cluster_id dominante por AGEB
    Economic Weight     — peso_total_ageb (continuo)
    Dominant Sector      — sector_dominante_nombre por AGEB (categórico,
                            top-12 + "Otros" solo por legibilidad de leyenda)
    Municipality         — geometría disuelta, cluster_dominante por municipio
    Simulation Impact    — impacto_propagado (continuo, solo si hay
                            simulación cargada en session_state)
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import geopandas as gpd
import plotly.graph_objects as go
import streamlit as st

from app.components.kpi import categorical_legend, grad_legend
from app.helpers.data_sources import AGEB_ID_COL, IMPACTO_PROPAGADO_COL
from app.helpers.formatting import color_for_hash, md, short_name

MAP_LAYER_OPTIONS = {
    "Economic Community": "community",
    "Economic Weight": "weight",
    "Dominant Sector": "sector",
    "Municipality": "municipality",
    "Simulation Impact": "impact",
}


def _ensure_state() -> None:
    st.session_state.setdefault("oe_map_layer", "Economic Community")


def _top_sector_buckets(ageb_gdf: gpd.GeoDataFrame, top_n: int = 12) -> list[str]:
    counts = ageb_gdf["sector_dominante_nombre"].value_counts()
    return counts.head(top_n).index.tolist()


def _community_traces(ctx: SimpleNamespace, gdf: gpd.GeoDataFrame) -> tuple[list, str]:
    traces = []
    for cid in sorted(gdf["cluster_id"].unique()):
        sub = gdf[gdf["cluster_id"] == cid]
        sub_geo = json.loads(sub.to_json())
        sel = st.session_state.get("oe_selected_ageb")
        is_dim = sub[AGEB_ID_COL].isin(ctx.dimmed_ids).all() if ctx.dimmed_ids else False
        traces.append(go.Choroplethmapbox(
            geojson=sub_geo, locations=sub.index, z=[1] * len(sub),
            colorscale=[[0, ctx.color_by_cluster.get(cid, "#576073")], [1, ctx.color_by_cluster.get(cid, "#576073")]],
            showscale=False,
            marker_opacity=0.25 if is_dim else 0.85,
            marker_line_width=0.2, marker_line_color="#0B0F17",
            name=short_name(ctx.nombre_by_cluster.get(cid, f"Cluster {cid}")),
            customdata=sub[[AGEB_ID_COL]].values,
            hovertemplate=(
                f"<b>{short_name(ctx.nombre_by_cluster.get(cid, f'Cluster {cid}'))}</b><br>"
                "AGEB %{customdata[0]}<extra></extra>"
            ),
        ))
    items = [(short_name(ctx.nombre_by_cluster.get(c, f"C{c}")), ctx.color_by_cluster.get(c, "#576073"))
             for c in sorted(gdf["cluster_id"].unique())][:10]
    return traces, categorical_legend("Comunidad económica dominante", items)


def _sector_traces(gdf: gpd.GeoDataFrame) -> tuple[list, str]:
    top_sectors = _top_sector_buckets(gdf)
    gdf = gdf.copy()
    gdf["_bucket"] = gdf["sector_dominante_nombre"].where(
        gdf["sector_dominante_nombre"].isin(top_sectors), "Otros"
    )
    traces = []
    buckets = sorted(gdf["_bucket"].unique(), key=lambda b: (b == "Otros", b))
    for bucket in buckets:
        sub = gdf[gdf["_bucket"] == bucket]
        sub_geo = json.loads(sub.to_json())
        color = "#576073" if bucket == "Otros" else color_for_hash(bucket)
        traces.append(go.Choroplethmapbox(
            geojson=sub_geo, locations=sub.index, z=[1] * len(sub),
            colorscale=[[0, color], [1, color]], showscale=False,
            marker_opacity=0.85, marker_line_width=0.2, marker_line_color="#0B0F17",
            name=bucket, customdata=sub[[AGEB_ID_COL]].values,
            hovertemplate=f"<b>{bucket}</b><br>AGEB %{{customdata[0]}}<extra></extra>",
        ))
    items = [(b, "#576073" if b == "Otros" else color_for_hash(b)) for b in buckets][:12]
    return traces, categorical_legend("Sector dominante (top 12 + Otros)", items)


def _weight_traces(gdf: gpd.GeoDataFrame) -> tuple[list, str]:
    vmin, vmax = float(gdf["peso_total_ageb"].min()), float(gdf["peso_total_ageb"].max())
    geo = json.loads(gdf.to_json())
    trace = go.Choroplethmapbox(
        geojson=geo, locations=gdf.index, z=gdf["peso_total_ageb"],
        colorscale="Blues", marker_opacity=0.85, marker_line_width=0.2,
        customdata=gdf[[AGEB_ID_COL]].values,
        hovertemplate="AGEB %{customdata[0]}<br>Peso: %{z:,.1f}<extra></extra>",
    )
    legend = grad_legend("Peso económico (AGEB)", vmin, vmax, "linear-gradient(90deg,#0d2b52,#3b82f6,#bfdbfe)")
    return [trace], legend


def _impact_traces(gdf: gpd.GeoDataFrame) -> tuple[list, str]:
    vmin, vmax = float(gdf[IMPACTO_PROPAGADO_COL].min()), float(gdf[IMPACTO_PROPAGADO_COL].max())
    geo = json.loads(gdf.to_json())
    trace = go.Choroplethmapbox(
        geojson=geo, locations=gdf.index, z=gdf[IMPACTO_PROPAGADO_COL],
        colorscale="Turbo", marker_opacity=0.85, marker_line_width=0.2,
        customdata=gdf[[AGEB_ID_COL]].values,
        hovertemplate="AGEB %{customdata[0]}<br>Impacto propagado: %{z:,.2f}<extra></extra>",
    )
    legend = grad_legend("Impacto propagado (simulación cargada)", vmin, vmax,
                          "linear-gradient(90deg,#30123b,#29bf12,#f9c80e)")
    return [trace], legend


def _municipality_traces(ctx: SimpleNamespace, muni_gdf: gpd.GeoDataFrame) -> tuple[list, str]:
    traces = []
    for cid in sorted(muni_gdf["cluster_dominante"].dropna().unique()):
        sub = muni_gdf[muni_gdf["cluster_dominante"] == cid]
        sub_geo = json.loads(sub.to_json())
        color = ctx.color_by_cluster.get(int(cid), "#576073")
        traces.append(go.Choroplethmapbox(
            geojson=sub_geo, locations=sub.index, z=[1] * len(sub),
            colorscale=[[0, color], [1, color]], showscale=False,
            marker_opacity=0.85, marker_line_width=0.4, marker_line_color="#0B0F17",
            name=short_name(ctx.nombre_by_cluster.get(int(cid), f"Cluster {cid}")),
            customdata=sub[["municipio"]].values,
            hovertemplate="Municipio %{customdata[0]}<extra></extra>",
        ))
    items = [(short_name(ctx.nombre_by_cluster.get(int(c), f"C{c}")), ctx.color_by_cluster.get(int(c), "#576073"))
             for c in sorted(muni_gdf["cluster_dominante"].dropna().unique())][:10]
    return traces, categorical_legend("Cluster dominante por municipio", items)


def render_map(ctx: SimpleNamespace) -> None:
    """`ctx` requiere: ageb_gdf_wgs84, muni_gdf_wgs84, color_by_cluster,
    nombre_by_cluster, shock_activo, dimmed_ids (set de cvegeo fuera del
    filtro activo, para atenuarlos sin ocultarlos)."""
    _ensure_state()

    options = list(MAP_LAYER_OPTIONS.keys())
    if not ctx.shock_activo:
        options = [o for o in options if o != "Simulation Impact"]
    if st.session_state["oe_map_layer"] not in options:
        st.session_state["oe_map_layer"] = options[0]

    layer_label = st.selectbox("Capa de mapa", options, key="oe_map_layer")
    layer_key = MAP_LAYER_OPTIONS[layer_label]

    if layer_key == "community":
        traces, legend_html = _community_traces(ctx, ctx.ageb_gdf_wgs84)
        id_col = AGEB_ID_COL
    elif layer_key == "weight":
        traces, legend_html = _weight_traces(ctx.ageb_gdf_wgs84)
        id_col = AGEB_ID_COL
    elif layer_key == "sector":
        traces, legend_html = _sector_traces(ctx.ageb_gdf_wgs84)
        id_col = AGEB_ID_COL
    elif layer_key == "municipality":
        traces, legend_html = _municipality_traces(ctx, ctx.muni_gdf_wgs84)
        id_col = "municipio"
    else:  # impact
        traces, legend_html = _impact_traces(ctx.ageb_gdf_wgs84)
        id_col = AGEB_ID_COL

    if not traces:
        st.markdown('<div class="empty-state">No hay datos para mostrar en esta capa.</div>', unsafe_allow_html=True)
        return

    centroid = ctx.ageb_gdf_wgs84.geometry.unary_union.centroid
    fig = go.Figure(data=traces)
    fig.update_layout(
        mapbox_style="carto-darkmatter", mapbox_zoom=8.2,
        mapbox_center={"lat": centroid.y, "lon": centroid.x},
        margin=dict(l=0, r=0, t=0, b=0), height=600,
        paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17",
        font=dict(family="Inter", color="#F4F5F7", size=11),
        legend=dict(bgcolor="rgba(16,21,31,0.85)", bordercolor="#212B3B", borderwidth=1,
                    font=dict(size=10), itemsizing="constant"),
        hoverlabel=dict(bgcolor="#171F2C", bordercolor="#212B3B", font=dict(color="#F4F5F7")),
        coloraxis_showscale=False,
    )

    map_event = st.plotly_chart(
        fig, use_container_width=True, config={"scrollZoom": True, "displaylogo": False},
        on_select="rerun", selection_mode=("points",), key=f"oe_map_{layer_key}",
    )
    if map_event and map_event.get("selection", {}).get("points"):
        pt = map_event["selection"]["points"][0]
        cdata = pt.get("customdata")
        if cdata:
            clicked_id = cdata[0]
            if id_col == "municipio":
                sub = ctx.ageb_gdf_wgs84[ctx.ageb_gdf_wgs84["municipio"] == clicked_id]
                if not sub.empty:
                    st.session_state["oe_selected_ageb"] = sub.sort_values(
                        "peso_total_ageb", ascending=False
                    ).iloc[0][AGEB_ID_COL]
            else:
                st.session_state["oe_selected_ageb"] = clicked_id
            st.rerun()

    md(legend_html)
