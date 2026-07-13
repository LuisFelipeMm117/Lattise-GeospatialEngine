# app/panels/territorial_context.py
"""
Opportunity Explorer — Capa 5 (Territorial Context).

Contexto municipal del AGEB seleccionado: municipio, AGEBs vecinas
(contigüidad espacial ya calculada por el Spatial Graph Builder,
`spatial.simulation.SpatialMatrix`, Stage 8A CERRADO), participación
municipal, diversidad sectorial y concentración económica — ambas
derivadas por aritmética simple (conteo / share) sobre columnas ya
existentes, sin ningún índice compuesto nuevo.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import streamlit as st

from app.components.kpi import render_kpi_grid, render_tag_row
from app.helpers.data_sources import AGEB_ID_COL, neighbors_of
from app.helpers.formatting import format_compact, format_pct, md, short_name


def render(ctx: SimpleNamespace, selected_ageb: Optional[str]) -> None:
    st.markdown('<div class="section-label">Territorial Context</div>', unsafe_allow_html=True)

    if selected_ageb is None:
        st.markdown('<div class="detail-empty">Selecciona un AGEB para ver su contexto territorial.</div>',
                     unsafe_allow_html=True)
        return

    row_df = ctx.ageb_df[ctx.ageb_df[AGEB_ID_COL] == selected_ageb]
    if row_df.empty:
        return
    row = row_df.iloc[0]

    muni_row_df = ctx.muni_summary[ctx.muni_summary["municipio"] == row["municipio"]]
    if muni_row_df.empty:
        st.info("Municipio sin resumen disponible.")
        return
    muni_row = muni_row_df.iloc[0]

    vecinos = neighbors_of(selected_ageb)
    vecinos_en_universo = [v for v in vecinos if v in set(ctx.ageb_df[AGEB_ID_COL])]

    # Concentración económica: share del sector dominante dentro del
    # peso total del propio AGEB (aritmética directa peso_sector/peso_total,
    # ambos ya calculados — no es un índice compuesto).
    peso_total = row.get("peso_total_ageb", 0) or 0
    concentracion = (row.get("sector_peso", 0) / peso_total * 100) if peso_total else 0.0

    md(f"""
    <div class="detail-sub">Municipio</div>
    <div class="detail-title">{row['municipio']}</div>
    """)

    render_kpi_grid([
        ("AGEBs en el municipio", str(int(muni_row["n_agebs"]))),
        ("Participación municipal", format_pct(muni_row["participacion_pct"])),
        ("Peso económico municipal", format_compact(muni_row["peso"])),
        ("Especialización municipal", short_name(muni_row["cluster_dominante_nombre"])),
        ("Diversidad sectorial (AGEB)", f"{int(row.get('n_sectores_ageb', 0))} sectores"),
        ("Concentración en sector dominante", format_pct(concentracion)),
    ])

    st.markdown('<div class="section-label">AGEBs vecinas (contigüidad espacial)</div>', unsafe_allow_html=True)
    if vecinos_en_universo:
        render_tag_row(vecinos_en_universo, max_tags=20)
        if len(vecinos_en_universo) < len(vecinos):
            st.caption(
                f"{len(vecinos) - len(vecinos_en_universo)} vecino(s) adicional(es) existen en la matriz "
                "espacial pero no tienen actividad registrada en el warehouse."
            )
    elif vecinos:
        st.caption("Los vecinos espaciales de este AGEB no tienen actividad económica registrada en el warehouse.")
    else:
        st.caption(
            "Sin matriz espacial disponible o AGEB sin vecinos registrados (posible isla). "
            "No se infiere vecindad geométrica en esta capa."
        )
