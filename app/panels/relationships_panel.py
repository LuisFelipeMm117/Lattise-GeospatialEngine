# app/panels/relationships_panel.py
"""
Opportunity Explorer — Capa 8 (Relationships).

Cadena jerárquica del AGEB seleccionado:
    AGEB → Municipio → Comunidad Económica → Sectores predominantes → AGEBs relacionadas

Toda la información ya existe en `ageb_gdf` / `community_summary` /
la matriz espacial (Stage 8A, CERRADO) — este panel solo la encadena
visualmente.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import streamlit as st

from app.helpers.data_sources import AGEB_ID_COL, neighbors_of
from app.helpers.formatting import md, short_name


def _node(label: str, value: str) -> str:
    return f'<div class="relationship-node"><span class="rn-label">{label}</span>{value}</div>'


def render(ctx: SimpleNamespace, selected_ageb: Optional[str]) -> None:
    st.markdown('<div class="section-label">Relationships</div>', unsafe_allow_html=True)

    if selected_ageb is None:
        st.markdown('<div class="detail-empty">Selecciona un AGEB para ver su cadena de relaciones territoriales.</div>',
                     unsafe_allow_html=True)
        return

    row_df = ctx.ageb_df[ctx.ageb_df[AGEB_ID_COL] == selected_ageb]
    if row_df.empty:
        return
    row = row_df.iloc[0]

    crow_df = ctx.community_summary[ctx.community_summary["cluster_id"] == row["cluster_id"]]
    community_name = short_name(crow_df.iloc[0]["nombre"]) if not crow_df.empty else "—"
    sectores = crow_df.iloc[0]["sectores"] if not crow_df.empty else []

    vecinos = [v for v in neighbors_of(selected_ageb) if v in set(ctx.ageb_df[AGEB_ID_COL])]
    vecinos_html = "".join(f'<span class="tag">{v}</span>' for v in vecinos[:12]) or (
        '<span class="tag">Sin vecinos registrados</span>'
    )
    sectores_html = "".join(f'<span class="tag">{s}</span>' for s in sectores[:10])

    chain = f"""
    <div class="relationship-chain">
      {_node("AGEB", row[AGEB_ID_COL])}
      <div class="relationship-arrow">↓</div>
      {_node("Municipio", row['municipio'])}
      <div class="relationship-arrow">↓</div>
      {_node("Comunidad económica", community_name)}
      <div class="relationship-arrow">↓</div>
      <div class="relationship-node">
        <span class="rn-label">Sectores predominantes</span>
        <div class="tag-row">{sectores_html}</div>
      </div>
      <div class="relationship-arrow">↓</div>
      <div class="relationship-node">
        <span class="rn-label">AGEBs relacionadas (contigüidad espacial)</span>
        <div class="tag-row">{vecinos_html}</div>
      </div>
    </div>
    """
    md(chain)
