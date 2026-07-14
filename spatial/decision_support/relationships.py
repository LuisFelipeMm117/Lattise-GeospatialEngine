# spatial/decision_support/relationships.py
"""
Decision Support Engine — Relaciones territoriales explícitas.

Construye, sin inferir nada nuevo, la cadena de relaciones que pide el
encargo:

    AGEB
      ↓ pertenece a Municipio
      ↓ pertenece a Comunidad económica
      ↓ relacionado con AGEBs (contigüidad espacial, Spatial Graph
        Builder — CERRADO)
      ↓ relacionado con Sectores (presencia registrada en
        `warehouse.parquet`)

Cada arista de esta cadena ya existe como columna en algún artefacto
congelado (`ageb_gdf` de `aggregation.build_ageb_universe`, `long_sector`,
o `SpatialMatrix.neighbors`) — este módulo únicamente las organiza en
una estructura de acceso directo (`dict` por AGEB/municipio/comunidad/
sector) y en una lista de aristas explícitas (`edges()`), sin ejecutar
ningún join geométrico nuevo ni releer `graph.gal`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import geopandas as gpd
import pandas as pd

from spatial.decision_support.constants import CLUSTER_ID_COL, ID_COL, MUNICIPIO_COL, SECTOR_SERIO_COL


@dataclass
class TerritorialRelationships:
    """Índices de acceso directo para cada arista de la cadena
    AGEB → Municipio → Comunidad → AGEBs relacionadas → Sectores."""

    ageb_to_municipio: dict = field(default_factory=dict)
    ageb_to_comunidad: dict = field(default_factory=dict)
    ageb_to_vecinos: dict = field(default_factory=dict)
    ageb_to_sectores: dict = field(default_factory=dict)

    municipio_to_agebs: dict = field(default_factory=dict)
    comunidad_to_agebs: dict = field(default_factory=dict)
    sector_to_agebs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def edges(self) -> list[dict]:
        """Lista plana de aristas explícitas `{origen, tipo, destino}` —
        una representación alternativa de los mismos índices, útil para
        exportar a un grafo (p.ej. NetworkX, o una tabla `.csv` de
        aristas) sin recorrer los diccionarios anidados a mano."""
        out: list[dict] = []
        for ageb, municipio in self.ageb_to_municipio.items():
            out.append({"origen": ageb, "tipo": "pertenece_a_municipio", "destino": municipio})
        for ageb, cluster_id in self.ageb_to_comunidad.items():
            if cluster_id is not None:
                out.append({"origen": ageb, "tipo": "pertenece_a_comunidad", "destino": cluster_id})
        for ageb, vecinos in self.ageb_to_vecinos.items():
            for vecino in vecinos:
                out.append({"origen": ageb, "tipo": "relacionado_con_ageb", "destino": vecino})
        for ageb, sectores in self.ageb_to_sectores.items():
            for sector in sectores:
                out.append({"origen": ageb, "tipo": "relacionado_con_sector", "destino": sector})
        return out


def build_territorial_relationships(
    ageb_gdf: gpd.GeoDataFrame,
    long_sector: pd.DataFrame,
    spatial_matrix=None,
    id_col: str = ID_COL,
    sector_col: str = SECTOR_SERIO_COL,
) -> TerritorialRelationships:
    """Ensambla `TerritorialRelationships` a partir de:
      - `ageb_gdf`      : salida de `aggregation.build_ageb_universe`
                          (columnas `id_col`, `municipio`, `cluster_id`).
      - `long_sector`   : salida de `aggregation.ageb_sector_weights`
                          (columnas `id_col`, `sector_col`).
      - `spatial_matrix`: `spatial.simulation.matrix.SpatialMatrix`
                          (Stage 8A, CERRADO) — OPCIONAL. Si es `None`,
                          `ageb_to_vecinos` queda vacío explícitamente
                          para cada AGEB (nunca se infiere vecindad por
                          proximidad geométrica ad hoc en esta capa,
                          mismo criterio que
                          `app/helpers/data_sources.py::neighbors_of`).
    """
    ageb_to_municipio = dict(zip(ageb_gdf[id_col], ageb_gdf[MUNICIPIO_COL]))
    ageb_to_comunidad = {
        row[id_col]: (int(row[CLUSTER_ID_COL]) if pd.notna(row[CLUSTER_ID_COL]) else None)
        for _, row in ageb_gdf.iterrows()
    }

    ageb_to_sectores: dict = {
        ageb: sorted(sub[sector_col].astype(str).tolist())
        for ageb, sub in long_sector.groupby(id_col)
    }

    ageb_to_vecinos: dict = {}
    for ageb in ageb_gdf[id_col]:
        if spatial_matrix is None:
            ageb_to_vecinos[ageb] = []
            continue
        try:
            ageb_to_vecinos[ageb] = list(spatial_matrix.neighbors_of(ageb))
        except KeyError:
            ageb_to_vecinos[ageb] = []

    municipio_to_agebs: dict = {}
    for ageb, municipio in ageb_to_municipio.items():
        municipio_to_agebs.setdefault(municipio, []).append(ageb)
    for municipio in municipio_to_agebs:
        municipio_to_agebs[municipio].sort()

    comunidad_to_agebs: dict = {}
    for ageb, cluster_id in ageb_to_comunidad.items():
        if cluster_id is None:
            continue
        comunidad_to_agebs.setdefault(cluster_id, []).append(ageb)
    for cluster_id in comunidad_to_agebs:
        comunidad_to_agebs[cluster_id].sort()

    sector_to_agebs: dict = {}
    for ageb, sectores in ageb_to_sectores.items():
        for sector in sectores:
            sector_to_agebs.setdefault(sector, []).append(ageb)
    for sector in sector_to_agebs:
        sector_to_agebs[sector].sort()

    return TerritorialRelationships(
        ageb_to_municipio=ageb_to_municipio,
        ageb_to_comunidad=ageb_to_comunidad,
        ageb_to_vecinos=ageb_to_vecinos,
        ageb_to_sectores=ageb_to_sectores,
        municipio_to_agebs=municipio_to_agebs,
        comunidad_to_agebs=comunidad_to_agebs,
        sector_to_agebs=sector_to_agebs,
    )


__all__ = ["TerritorialRelationships", "build_territorial_relationships"]
