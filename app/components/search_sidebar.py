# app/components/search_sidebar.py
"""
Opportunity Explorer — Capa 1 (Search / Filters / Explorer).

Resuelve búsqueda por AGEB, Municipio, Sector o Comunidad económica
sobre las tablas ya construidas por `app.helpers.aggregation`. Nunca
recalcula nada: solo filtra/ordena y actualiza el `st.session_state`
que sirve de fuente única de verdad para mapa + paneles (mismo patrón
`session_state`-como-fuente-de-verdad ya usado en Run Simulation).

Estado gestionado (namespace `oe_` — independiente del `session_state`
de Spatial Cluster Intelligence, para no interferir entre páginas):
    oe_selected_ageb     : Optional[str]  — AGEB activo (fuente de verdad)
    oe_filter_municipios : list[str]      — filtro activo (Explorer + mapa)
    oe_filter_clusters   : list[int]      — filtro activo (Explorer + mapa)
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import streamlit as st

from app.helpers.data_sources import AGEB_ID_COL
from app.helpers.formatting import format_compact, format_pct, md, short_name


def _ensure_state() -> None:
    st.session_state.setdefault("oe_selected_ageb", None)
    st.session_state.setdefault("oe_filter_municipios", [])
    st.session_state.setdefault("oe_filter_clusters", [])


def _top_ageb_in(ageb_df: pd.DataFrame, mask: pd.Series) -> str | None:
    sub = ageb_df[mask]
    if sub.empty:
        return None
    return sub.sort_values("peso_total_ageb", ascending=False).iloc[0][AGEB_ID_COL]


def _resolve_query(query: str, ctx: SimpleNamespace) -> tuple[str | None, str]:
    """Devuelve (ageb_id_a_seleccionar, mensaje_de_resolución)."""
    q = query.strip().lower()
    ageb_df = ctx.ageb_df

    ageb_hits = ageb_df[ageb_df[AGEB_ID_COL].str.lower().str.contains(q, na=False)]
    if ageb_hits[AGEB_ID_COL].nunique() == 1:
        return ageb_hits.iloc[0][AGEB_ID_COL], "AGEB"

    muni_hits = sorted({m for m in ageb_df["municipio"].unique() if q in str(m).lower()})
    if len(muni_hits) == 1:
        sel = _top_ageb_in(ageb_df, ageb_df["municipio"] == muni_hits[0])
        return sel, f"Municipio {muni_hits[0]}"

    cluster_hits = ctx.community_summary[
        ctx.community_summary["nombre"].str.lower().str.contains(q, na=False)
        | ctx.community_summary["sectores"].apply(lambda ss: any(q in s.lower() for s in ss))
    ]
    if cluster_hits["cluster_id"].nunique() == 1:
        cid = int(cluster_hits.iloc[0]["cluster_id"])
        sel = _top_ageb_in(ageb_df, ageb_df["cluster_id"] == cid)
        return sel, f"Comunidad {short_name(cluster_hits.iloc[0]['nombre'])}"

    sector_hits = ageb_df[ageb_df["sector_dominante_nombre"].str.lower().str.contains(q, na=False)]
    if not sector_hits.empty:
        sel = _top_ageb_in(ageb_df, ageb_df["sector_dominante_nombre"].str.lower().str.contains(q, na=False))
        return sel, f"Sector — {sector_hits.iloc[0]['sector_dominante_nombre']}"

    return None, ""


def render_search_and_filters(ctx: SimpleNamespace) -> None:
    """Dibuja Search + Filters. `ctx` requiere: ageb_df, community_summary,
    muni_summary. Actualiza `st.session_state` directamente."""
    _ensure_state()

    st.markdown('<div class="section-label">Buscar</div>', unsafe_allow_html=True)
    query = st.text_input(
        "Buscar AGEB, municipio, sector o comunidad", key="oe_query",
        placeholder="🔎 AGEB, municipio, sector, comunidad…", label_visibility="collapsed",
    )
    if query.strip():
        sel, label = _resolve_query(query, ctx)
        if sel is not None:
            st.session_state["oe_selected_ageb"] = sel
            st.caption(f"✓ Coincidencia: {label}")
        else:
            st.caption("Sin coincidencias únicas.")

    st.markdown('<div class="section-label">Filtros</div>', unsafe_allow_html=True)
    muni_options = sorted(ctx.ageb_df["municipio"].unique().tolist())
    st.session_state["oe_filter_municipios"] = st.multiselect(
        "Municipio", muni_options, default=st.session_state["oe_filter_municipios"], key="oe_muni_filter",
    )
    cluster_labels = {
        int(r["cluster_id"]): short_name(r["nombre"]) for _, r in ctx.community_summary.iterrows()
    }
    sel_cluster_labels = st.multiselect(
        "Comunidad económica", list(cluster_labels.values()),
        default=[cluster_labels[c] for c in st.session_state["oe_filter_clusters"] if c in cluster_labels],
        key="oe_cluster_filter",
    )
    inv_labels = {v: k for k, v in cluster_labels.items()}
    st.session_state["oe_filter_clusters"] = [inv_labels[lbl] for lbl in sel_cluster_labels]


def apply_filters(ageb_df: pd.DataFrame) -> pd.DataFrame:
    df = ageb_df
    munis = st.session_state.get("oe_filter_municipios") or []
    clusters = st.session_state.get("oe_filter_clusters") or []
    if munis:
        df = df[df["municipio"].isin(munis)]
    if clusters:
        df = df[df["cluster_id"].isin(clusters)]
    return df


def render_explorer_list(ctx: SimpleNamespace, filtered_ageb_df: pd.DataFrame, top_n: int = 15) -> None:
    """Capa 1 · Explorer — lista navegable de AGEB ordenados por peso
    económico dentro del filtro/búsqueda activos."""
    st.markdown('<div class="section-label">Explorer</div>', unsafe_allow_html=True)
    if filtered_ageb_df.empty:
        st.caption("Sin AGEB que coincidan con los filtros activos.")
        return

    ranked = filtered_ageb_df.sort_values("peso_total_ageb", ascending=False).head(top_n)
    selected = st.session_state.get("oe_selected_ageb")
    for _, row in ranked.iterrows():
        cid = int(row["cluster_id"])
        color = ctx.color_by_cluster.get(cid, "#576073")
        is_sel = row[AGEB_ID_COL] == selected
        card_cls = "oe-card active" if is_sel else "oe-card"
        md(f"""
        <div class="{card_cls}">
          <div class="oe-card-head">
            <div class="oe-dot" style="background:{color};"></div>
            <div class="oe-card-name">{row[AGEB_ID_COL]}</div>
          </div>
          <div class="oe-card-meta">Mun. {row['municipio']} · {format_compact(row['peso_total_ageb'])} · {format_pct(row['participacion_pct'])}</div>
        </div>
        """)
        if st.button("Ver perfil", key=f"oe_pick_{row[AGEB_ID_COL]}", use_container_width=True):
            st.session_state["oe_selected_ageb"] = row[AGEB_ID_COL]
            st.rerun()
