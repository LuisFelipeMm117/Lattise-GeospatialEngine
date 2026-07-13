# app/panels/insights_panel.py
"""
Opportunity Explorer — Capa 7 (Insights).

Únicamente insights descriptivos, generados con reglas determinísticas
(`app.helpers.insights`) — nunca recomendaciones, nunca IA.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import streamlit as st

from app.helpers.aggregation import ageb_direct_shock
from app.helpers.data_sources import AGEB_ID_COL, neighbors_of
from app.helpers.formatting import md
from app.helpers.insights import (
    generate_profile_insights,
    generate_shock_insights,
    generate_statistics_insights,
    generate_territory_insights,
)


def render(ctx: SimpleNamespace, selected_ageb: Optional[str]) -> None:
    st.markdown('<div class="section-label">Insights</div>', unsafe_allow_html=True)

    cards: list[tuple[str, str]] = []  # (texto, css_class)

    if selected_ageb is not None:
        row_df = ctx.ageb_df[ctx.ageb_df[AGEB_ID_COL] == selected_ageb]
        if not row_df.empty:
            row = row_df.iloc[0]
            crow_df = ctx.community_summary[ctx.community_summary["cluster_id"] == row["cluster_id"]]
            if not crow_df.empty:
                for txt in generate_profile_insights(row, crow_df.iloc[0], len(ctx.ageb_df)):
                    cards.append((txt, ""))

            muni_row_df = ctx.muni_summary[ctx.muni_summary["municipio"] == row["municipio"]]
            if not muni_row_df.empty:
                n_vecinos = len([v for v in neighbors_of(selected_ageb) if v in set(ctx.ageb_df[AGEB_ID_COL])])
                for txt in generate_territory_insights(muni_row_df.iloc[0], n_vecinos):
                    cards.append((txt, ""))

            shock = ageb_direct_shock(ctx.sim_gdf, selected_ageb)
            if shock is not None:
                for txt in generate_shock_insights(shock):
                    cards.append((txt, "shock"))

    for txt in generate_statistics_insights(ctx.ageb_df):
        cards.append((txt, ""))

    if not cards:
        st.caption("Selecciona un AGEB para generar insights de su perfil territorial.")
        return

    for txt, cls in cards:
        md(f'<div class="insight-card {cls}">{txt}</div>')
