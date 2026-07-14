# spatial/decision_support/insights.py
"""
Decision Support Engine — Insights descriptivos.

Reglas determinísticas de DESCRIPCIÓN, nunca de recomendación:
    - Nunca responden "¿dónde invertir?" ni "¿cuál es la mejor
      ubicación?" (esa responsabilidad es exclusiva del frontend, ver
      encabezado de `report.py`).
    - Nunca infieren, pronostican, optimizan ni usan IA/ML.
    - Cada función solo lee campos que YA existen en los `dataclasses`
      de `spatial.decision_support.profiles` — ningún valor nuevo se
      calcula aquí, solo se redacta en español.

Mismo criterio ya usado por `app/helpers/insights.py`
(`generate_profile_insights`, `generate_community_insights`, ...),
adaptado para operar sobre `AGEBProfile` / `MunicipalityProfile` /
`CommunityProfile` en vez de `pd.Series` sueltas, y sin ninguna
dependencia de `streamlit`.
"""
from __future__ import annotations

from typing import Optional

from spatial.decision_support.formatting import format_compact, format_pct, short_name
from spatial.decision_support.profiles import AGEBProfile, CommunityProfile, MunicipalityProfile


def ageb_insights(profile: AGEBProfile) -> list[str]:
    """Insights descriptivos de un `AGEBProfile` puntual."""
    out: list[str] = []
    cluster_txt = short_name(profile.cluster_nombre) if profile.cluster_nombre else "sin comunidad asignada"
    out.append(
        f"El AGEB {profile.ageb} pertenece al municipio {profile.municipio} "
        f"y su comunidad económica dominante es {cluster_txt}."
    )
    if profile.sector_dominante_nombre:
        out.append(
            f"El sector predominante es {profile.sector_dominante_nombre}, "
            f"dentro de un total de {profile.n_sectores} sector(es) con presencia registrada."
        )
    if profile.ranking is not None:
        out.append(
            f"Representa el {format_pct(profile.participacion_pct)} del peso económico territorial "
            f"(ranking #{profile.ranking} de {profile.n_agebs_universo})."
        )
    if profile.impacto_propagado is not None:
        out.append(
            f"El impacto directo simulado en este AGEB es {format_compact(profile.impacto_directo)}, "
            f"con un impacto total propagado de {format_compact(profile.impacto_propagado)}."
        )
        if profile.impacto_propagado and abs(profile.impacto_propagado) > 1e-9 and profile.impacto_indirecto is not None:
            share_indirecto = abs(profile.impacto_indirecto) / abs(profile.impacto_propagado) * 100
            out.append(f"El {share_indirecto:.0f}% del impacto propagado corresponde a efectos indirectos.")
    if profile.n_vecinos:
        out.append(
            f"Tiene {profile.n_vecinos} AGEB(s) vecino(s) por contigüidad espacial, "
            f"conectados con {len(profile.municipios_conectados)} municipio(s) "
            f"y {len(profile.comunidades_relacionadas)} comunidad(es) económica(s)."
        )
    elif profile.es_isla:
        out.append("No hay AGEBs vecinas registradas en la matriz espacial para este AGEB (isla espacial).")
    return out


def municipality_insights(profile: MunicipalityProfile) -> list[str]:
    out: list[str] = []
    out.append(
        f"El municipio {profile.municipio} concentra el {format_pct(profile.participacion_pct)} "
        f"del peso económico territorial, con {profile.n_agebs} AGEB(s) registrado(s)."
    )
    if profile.clusters_presentes:
        out.append(
            f"Presenta actividad de {len(profile.clusters_presentes)} comunidad(es) económica(s) "
            f"y {len(profile.sectores_presentes)} sector(es) distintos."
        )
    if profile.impacto_propagado_agregado is not None:
        out.append(
            f"El impacto propagado agregado de la simulación cargada es "
            f"{format_compact(profile.impacto_propagado_agregado)} "
            f"({format_compact(profile.impacto_propagado_promedio)} promedio por AGEB)."
        )
    return out


def community_insights(profile: CommunityProfile) -> list[str]:
    out: list[str] = []
    out.append(
        f"La comunidad {short_name(profile.nombre)} concentra el {format_pct(profile.participacion_pct)} "
        f"del peso económico territorial ({profile.n_agebs} AGEB, {profile.n_sectores} sectores, "
        f"{profile.n_municipios} municipio(s))."
    )
    if profile.municipios_principales:
        out.append(
            f"Sus municipios principales son: {', '.join(profile.municipios_principales[:5])}."
        )
    return out


def portfolio_insights(community_profiles: list[CommunityProfile]) -> list[str]:
    """Insights descriptivos a nivel del territorio completo (todas las
    comunidades juntas) — mismo criterio de "concentración acumulada"
    que `app/helpers/insights.py::generate_community_insights`."""
    out: list[str] = []
    if not community_profiles:
        return out
    ordered = sorted(community_profiles, key=lambda c: c.participacion_pct, reverse=True)
    top = ordered[0]
    out.append(
        f"La comunidad {short_name(top.nombre)} contiene {top.n_agebs} AGEB(s) y concentra el "
        f"{format_pct(top.participacion_pct)} del peso económico territorial."
    )
    cum = 0.0
    n_top = 0
    for c in ordered:
        cum += c.participacion_pct
        n_top += 1
        if cum >= 80.0:
            break
    out.append(
        f"Las {n_top} comunidad(es) principal(es) representan el {cum:.0f}% de la actividad registrada."
    )
    return out


__all__ = [
    "ageb_insights",
    "municipality_insights",
    "community_insights",
    "portfolio_insights",
]
