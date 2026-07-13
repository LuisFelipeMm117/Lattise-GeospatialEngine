# app/panels/community_profile.py
"""
Opportunity Explorer — Capa 4 (Community Profile).

Perfil de la comunidad económica dominante del AGEB seleccionado.
Reutiliza exclusivamente `community_summary` (mismo cálculo que
`build_community_summary` en Spatial Cluster Intelligence) y el
`ageb_gdf` ya construido — sin recorrer Louvain de nuevo.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import plotly.express as px
import streamlit as st

from app.components.kpi import render_kpi_grid, render_tag_row
from app.helpers.data_sources import AGEB_ID_COL
from app.helpers.formatting import format_compact, format_pct, md, short_name


def render(ctx: SimpleNamespace, selected_ageb: Optional[str]) -> None:
    st.markdown('<div class="section-label">Community Profile</div>', unsafe_allow_html=True)

    if selected_ageb is None:
        st.markdown('<div class="detail-empty">Selecciona un AGEB para ver el perfil de su comunidad económica.</div>',
                     unsafe_allow_html=True)
        return

    row = ctx.ageb_df[ctx.ageb_df[AGEB_ID_COL] == selected_ageb]
    if row.empty:
        return
    cluster_id = int(row.iloc[0]["cluster_id"])
    crow_df = ctx.community_summary[ctx.community_summary["cluster_id"] == cluster_id]
    if crow_df.empty:
        st.info("Comunidad sin resumen disponible.")
        return
    crow = crow_df.iloc[0]

    md(f"""
    <div class="detail-sub">Comunidad {cluster_id}</div>
    <div class="detail-title" style="color:{crow['color']};">{short_name(crow['nombre'])}</div>
    """)

    render_kpi_grid([
        ("AGEBs", str(int(crow["n_agebs"]))),
        ("Municipios", str(int(crow["n_municipios"]))),
        ("Sectores", str(int(crow["n_sectores"]))),
        ("Participación", format_pct(crow["participacion_pct"])),
        ("Peso económico", format_compact(crow["peso_economico"])),
        ("Centralidad media", f"{crow['centralidad_media']:.3f}"),
    ])

    st.markdown('<div class="section-label">Sectores predominantes</div>', unsafe_allow_html=True)
    render_tag_row(crow["sectores"])

    st.markdown('<div class="section-label">Municipios presentes</div>', unsafe_allow_html=True)
    render_tag_row([f"Mun. {m}" for m in crow["municipios"]])

    st.markdown('<div class="section-label">AGEBs principales de la comunidad</div>', unsafe_allow_html=True)
    top_agebs = (
        ctx.ageb_df[ctx.ageb_df["cluster_id"] == cluster_id]
        .sort_values("peso_total_ageb", ascending=False)
        .head(10)
    )
    if top_agebs.empty:
        st.caption("Sin AGEBs para listar.")
    else:
        fig = px.bar(
            top_agebs, x="peso_total_ageb", y=AGEB_ID_COL, orientation="h",
            color="peso_total_ageb", color_continuous_scale="Blues",
            labels={"peso_total_ageb": "Peso económico", AGEB_ID_COL: ""},
            title="Top 10 AGEBs por peso económico",
        )
        fig.update_layout(
            yaxis=dict(autorange="reversed"), height=340,
            paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17", font_color="#F4F5F7",
            margin=dict(l=0, r=0, t=40, b=0), title_font_size=12, coloraxis_showscale=False,
        )
        st.plotly_chart(fig, use_container_width=True)
