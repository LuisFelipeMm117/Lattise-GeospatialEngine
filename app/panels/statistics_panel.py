# app/panels/statistics_panel.py
"""
Opportunity Explorer — Capa 6 (Statistics).

Panel compacto de estadística descriptiva estándar (histograma,
percentiles, top-N, conteos) sobre `ageb_gdf` / `community_summary` /
`muni_summary`. Estadística descriptiva pura — ningún modelo, ningún
índice compuesto nuevo.
"""
from __future__ import annotations

from types import SimpleNamespace

import plotly.express as px
import streamlit as st

from app.helpers.data_sources import AGEB_ID_COL
from app.helpers.formatting import format_compact, short_name

_CHART_LAYOUT = dict(
    paper_bgcolor="#0B0F17", plot_bgcolor="#0B0F17", font_color="#F4F5F7",
    margin=dict(l=0, r=0, t=40, b=0), title_font_size=12,
)


def render(ctx: SimpleNamespace) -> None:
    st.markdown('<div class="section-label">Statistics</div>', unsafe_allow_html=True)

    ageb_df = ctx.ageb_df
    if ageb_df.empty:
        st.caption("Sin datos para mostrar.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AGEBs totales", ageb_df[AGEB_ID_COL].nunique())
    c2.metric("Municipios", ageb_df["municipio"].nunique())
    c3.metric("Comunidades", ageb_df["cluster_id"].nunique())
    c4.metric("Sectores dominantes distintos", ageb_df["sector_dominante_nombre"].nunique())

    col_a, col_b = st.columns(2)
    with col_a:
        fig_hist = px.histogram(
            ageb_df, x="peso_total_ageb", nbins=25,
            title="Distribución del peso económico por AGEB",
            labels={"peso_total_ageb": "Peso económico"},
        )
        fig_hist.update_layout(height=340, **_CHART_LAYOUT)
        st.plotly_chart(fig_hist, use_container_width=True)

        pct = ageb_df["peso_total_ageb"].quantile([0.10, 0.25, 0.50, 0.75, 0.90, 0.99])
        st.caption(
            "Percentiles de peso económico — "
            f"P10: {format_compact(pct.loc[0.10])} · P50: {format_compact(pct.loc[0.50])} · "
            f"P90: {format_compact(pct.loc[0.90])} · P99: {format_compact(pct.loc[0.99])}"
        )

    with col_b:
        top_sectores = ageb_df["sector_dominante_nombre"].value_counts().head(10).reset_index()
        top_sectores.columns = ["sector", "n_agebs"]
        fig_sec = px.bar(
            top_sectores.sort_values("n_agebs"), x="n_agebs", y="sector", orientation="h",
            color="n_agebs", color_continuous_scale="Purples",
            title="Top 10 sectores dominantes por # de AGEB",
            labels={"n_agebs": "AGEBs", "sector": ""},
        )
        fig_sec.update_layout(height=340, coloraxis_showscale=False, **_CHART_LAYOUT)
        st.plotly_chart(fig_sec, use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        top_muni = ageb_df.groupby("municipio", as_index=False)[AGEB_ID_COL].nunique().rename(
            columns={AGEB_ID_COL: "n_agebs"}
        ).sort_values("n_agebs", ascending=False).head(12)
        fig_muni = px.bar(
            top_muni.sort_values("n_agebs"), x="n_agebs", y="municipio", orientation="h",
            color="n_agebs", color_continuous_scale="Blues",
            title="Top municipios por # de AGEB",
            labels={"n_agebs": "AGEBs", "municipio": ""},
        )
        fig_muni.update_layout(height=340, coloraxis_showscale=False, **_CHART_LAYOUT)
        st.plotly_chart(fig_muni, use_container_width=True)

    with col_d:
        df_tree = ctx.community_summary.copy()
        df_tree["nombre_corto"] = df_tree["nombre"].map(short_name)
        fig_tree = px.treemap(
            df_tree, path=["nombre_corto"], values="peso_economico", color="participacion_pct",
            color_continuous_scale="Blues", title="Peso económico por comunidad",
        )
        fig_tree.update_layout(height=340, **_CHART_LAYOUT)
        st.plotly_chart(fig_tree, use_container_width=True)
