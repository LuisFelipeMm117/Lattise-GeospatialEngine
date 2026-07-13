# app/helpers/insights.py
"""
Opportunity Explorer — Insights (Capa 7).

Reglas determinísticas de descripción, no de recomendación. Cada
función solo lee columnas que ya existen en los DataFrames construidos
por `app.helpers.aggregation` — ningún valor se infiere, pronostica ni
genera con IA. Mismo criterio ya usado por
`generate_structural_insights` / `generate_municipality_insights` en
Spatial Cluster Intelligence, adaptado al perfil de un AGEB puntual.
"""
from __future__ import annotations

import pandas as pd

from app.helpers.data_sources import (
    AGEB_ID_COL,
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
)
from app.helpers.formatting import format_compact, format_pct, short_name


def generate_profile_insights(ageb_row: pd.Series, community_row: pd.Series, n_total_agebs: int) -> list[str]:
    """Insights descriptivos para el AGEB seleccionado (Opportunity Profile)."""
    out: list[str] = []
    out.append(
        f"El AGEB <b>{ageb_row['cvegeo']}</b> pertenece al municipio <b>{ageb_row['municipio']}</b> "
        f"y su comunidad económica dominante es <b>{short_name(community_row['nombre'])}</b>."
    )
    out.append(
        f"El sector predominante es <b>{ageb_row.get('sector_dominante_nombre', '—')}</b>, "
        f"dentro de un total de <b>{int(ageb_row.get('n_sectores_ageb', 0))}</b> sectores con presencia registrada."
    )
    out.append(
        f"Representa el <b>{format_pct(ageb_row.get('participacion_pct', 0))}</b> del peso económico territorial "
        f"(ranking estatal #{int(ageb_row.get('ranking_estatal', 0))} de {n_total_agebs})."
    )
    return out


def generate_community_insights(summary: pd.DataFrame) -> list[str]:
    out: list[str] = []
    if summary.empty:
        return out
    top = summary.iloc[0]
    out.append(
        f"La comunidad <b>{short_name(top['nombre'])}</b> concentra el "
        f"<b>{format_pct(top['participacion_pct'])}</b> del peso económico territorial "
        f"({int(top['n_agebs'])} AGEB, {int(top['n_sectores'])} sectores)."
    )
    cum = summary["participacion_pct"].cumsum()
    n_top = min(int((cum < 80).sum()) + 1, len(summary))
    out.append(
        f"Las <b>{n_top}</b> comunidades principales representan el "
        f"<b>{cum.iloc[n_top-1]:.0f}%</b> de la actividad registrada."
    )
    return out


def generate_selected_community_insights(row: pd.Series) -> list[str]:
    out = []
    out.append(
        f"Esta comunidad representa el <b>{format_pct(row['participacion_pct'])}</b> del peso económico "
        f"territorial total."
    )
    out.append(f"El sector con mayor centralidad de la comunidad es <b>{row['sectores'][0] if row['sectores'] else '—'}</b>.")
    out.append(f"Participan <b>{int(row['n_municipios'])}</b> municipios.")
    out.append(f"Contiene <b>{int(row['n_agebs'])}</b> AGEBs.")
    return out


def generate_territory_insights(muni_row: pd.Series, n_agebs_vecinas: int) -> list[str]:
    out = []
    out.append(
        f"El municipio <b>{muni_row['municipio']}</b> concentra el "
        f"<b>{format_pct(muni_row['participacion_pct'])}</b> del peso económico territorial, con "
        f"<b>{int(muni_row['n_agebs'])}</b> AGEB registrados."
    )
    out.append(
        f"Su especialización dominante es <b>{short_name(muni_row['cluster_dominante_nombre'])}</b>."
    )
    if n_agebs_vecinas:
        out.append(f"El AGEB seleccionado tiene <b>{n_agebs_vecinas}</b> AGEB vecino(s) por contigüidad espacial.")
    else:
        out.append("No hay AGEBs vecinas registradas en la matriz espacial para esta selección (posible isla).")
    return out


def generate_shock_insights(shock: dict) -> list[str]:
    out = []
    directo = shock.get(IMPACTO_DIRECTO_COL, 0.0)
    propagado = shock.get(IMPACTO_PROPAGADO_COL, 0.0)
    indirecto = shock.get(IMPACTO_INDIRECTO_COL, 0.0)
    out.append(
        f"El impacto directo simulado en este AGEB es <b>{format_compact(directo)}</b>, con un impacto "
        f"total propagado de <b>{format_compact(propagado)}</b>."
    )
    if abs(propagado) > 1e-9:
        share_indirecto = abs(indirecto) / abs(propagado) * 100
        out.append(f"El <b>{share_indirecto:.0f}%</b> del impacto propagado corresponde a efectos indirectos.")
    return out


def generate_statistics_insights(ageb_gdf: pd.DataFrame) -> list[str]:
    out = []
    if ageb_gdf.empty:
        return out
    p90 = ageb_gdf["peso_total_ageb"].quantile(0.90)
    n_top10 = int((ageb_gdf["peso_total_ageb"] >= p90).sum())
    out.append(
        f"<b>{n_top10}</b> AGEB(s) concentran el 10% superior de peso económico "
        f"(umbral P90 = {format_compact(p90)})."
    )
    n_agebs = ageb_gdf[AGEB_ID_COL].nunique() if AGEB_ID_COL in ageb_gdf.columns else len(ageb_gdf)
    out.append(f"El territorio registra <b>{n_agebs}</b> AGEB(s) con actividad económica.")
    return out
