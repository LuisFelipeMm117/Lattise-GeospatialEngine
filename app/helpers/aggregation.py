# app/helpers/aggregation.py
"""
Opportunity Explorer — lectura puntual de shock ya calculado.

Historial: hasta este refactor, este archivo también reimplementaba
`build_ageb_universe`, `ageb_cluster_weights`, `ageb_sector_weights`,
`build_community_summary`, `build_municipality_gdf` y
`build_municipality_summary` — una segunda copia de la lógica de peso/
comunidad/sector dominante que YA vive, cerrada y probada, en
`spatial.decision_support` (ver `tests/test_decision_support.py`). Esa
duplicación quedó eliminada: toda esa construcción ahora pasa
exclusivamente por `app.helpers.decision_support_bridge.build_universe`,
que envuelve `spatial.decision_support.build_decision_support_report`.

Lo único que queda aquí es una lectura directa (sin agregación, sin
argmax, sin groupby) de una columna puntual de `simulation_gdf` para un
único AGEB — no era una duplicación del motor, solo un `.loc` con
formato, y varios paneles (`opportunity_profile.py`, `insights_panel.py`)
lo llaman directamente sobre `ctx.sim_gdf`, que es más barato que
recorrer todo `ageb_df` para leer tres números.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd

from app.helpers.data_sources import (
    AGEB_ID_COL,
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
)


def ageb_direct_shock(sim_gdf: Optional[gpd.GeoDataFrame], cvegeo: str) -> Optional[dict]:
    """Lectura directa (sin agregación) del impacto ya calculado para un
    AGEB puntual en `simulation_gdf` (Stage 8C, CERRADO)."""
    if sim_gdf is None:
        return None
    row = sim_gdf[sim_gdf[AGEB_ID_COL] == cvegeo]
    if row.empty:
        return None
    row = row.iloc[0]
    return {
        IMPACTO_DIRECTO_COL: float(row[IMPACTO_DIRECTO_COL]),
        IMPACTO_INDIRECTO_COL: float(row[IMPACTO_INDIRECTO_COL]),
        IMPACTO_PROPAGADO_COL: float(row[IMPACTO_PROPAGADO_COL]),
    }


__all__ = ["ageb_direct_shock"]
