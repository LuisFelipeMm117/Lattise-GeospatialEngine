# app/panels/opportunity_profile.py
"""
Opportunity Explorer — Capa 3 (Opportunity Profile).

Perfil territorial de un AGEB puntual. Todos los valores mostrados ya
existen en `ageb_gdf` / `community_summary` / `simulation_gdf` — este
módulo únicamente selecciona la fila y la formatea. No calcula ningún
indicador nuevo (no hay Opportunity Score aquí).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import streamlit as st

from app.components.kpi import render_kpi_grid, render_tag_row
from app.helpers.aggregation import ageb_direct_shock
from app.helpers.data_sources import AGEB_ID_COL
from app.helpers.formatting import format_compact, format_pct, md, short_name


def render(ctx: SimpleNamespace, selected_ageb: Optional[str]) -> None:
    st.markdown('<div class="section-label">Opportunity Profile</div>', unsafe_allow_html=True)

    if selected_ageb is None:
        st.markdown(
            '<div class="detail-empty">Selecciona un AGEB en el mapa, en el Explorer o mediante la búsqueda '
            'para ver su perfil territorial.</div>', unsafe_allow_html=True,
        )
        return

    row = ctx.ageb_df[ctx.ageb_df[AGEB_ID_COL] == selected_ageb]
    if row.empty:
        st.markdown('<div class="detail-empty">AGEB no encontrado en el universo actual.</div>', unsafe_allow_html=True)
        return
    row = row.iloc[0]

    community_row = ctx.community_summary[ctx.community_summary["cluster_id"] == row["cluster_id"]]
    community_name = short_name(community_row.iloc[0]["nombre"]) if not community_row.empty else "—"
    color = ctx.color_by_cluster.get(int(row["cluster_id"]), "#576073")

    md(f"""
    <div class="detail-sub">AGEB</div>
    <div class="detail-title">{row[AGEB_ID_COL]}</div>
    """)
    render_tag_row([
        f"Municipio {row['municipio']}",
        f'<span style="color:{color};">{community_name}</span>',
        f"Sector: {row.get('sector_dominante_nombre', '—')}",
    ])

    render_kpi_grid([
        ("Comunidad económica", community_name),
        ("Sector dominante", row.get("sector_dominante_nombre", "—")),
        ("N° sectores presentes", str(int(row.get("n_sectores_ageb", 0)))),
        ("Participación territorial", format_pct(row.get("participacion_pct", 0))),
        ("Peso económico", format_compact(row.get("peso_total_ageb", 0))),
        ("Ranking estatal", f"#{int(row.get('ranking_estatal', 0))} de {len(ctx.ageb_df)}"),
    ])

    shock = ageb_direct_shock(ctx.sim_gdf, selected_ageb)
    if shock is not None:
        st.markdown('<div class="section-label">Impacto de simulación (Run Simulation)</div>', unsafe_allow_html=True)
        render_kpi_grid([
            ("Impacto directo", format_compact(shock["shock_directo"])),
            ("Impacto indirecto", format_compact(shock["impacto_indirecto"])),
            ("Impacto propagado", format_compact(shock["impacto_propagado"])),
        ])
    else:
        st.caption("Sin simulación cargada — corre un shock en Run Simulation para ver impacto directo/propagado.")
