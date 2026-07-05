# spatial/allocation/weights.py
"""
Weights — Capa de acceso a ω (Especificación Formal v3.0, Sección 8, Stage 7).

Responsabilidad:
    Exponer funciones de LECTURA sobre ω_{g,s} tal como quedó calculado por
    `WarehouseBuilder.compute_weights()` (Stage 5) y persistido en
    `warehouse.parquet`. Este módulo NO calcula, recalcula ni normaliza ω
    bajo ninguna circunstancia — únicamente organiza el acceso a la columna
    ya existente (`omega`) y a su trazabilidad (`omega_metodo`), con el
    mismo criterio de Layer Isolation y Explicit Data Contracts (Sección 5)
    usado en Stage 1→6:
        - Ningún AGEB sin ω calculable ('omega_metodo' == 'sin_datos') se
          descarta en silencio: `omega_for()` los excluye del reparto (no
          hay peso que usar), pero `n_agebs_sin_omega()` los cuenta aparte.
        - La geometría se conserva (una fila por AGEB, deduplicada) para
          que `allocator.py` pueda anexarla a `shock_ageb.parquet` sin
          releer ni reconstruir el warehouse.

Depende de (solo como consumidor de su artefacto, no como caller):
    - spatial.warehouse.builder.WarehouseBuilder   (Stage 5 — LISTO)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

from spatial.config import AGEB_ID_COL, WAREHOUSE_PARQUET
from spatial.warehouse.builder import SECTOR_COL

logger = logging.getLogger("sew.allocation.weights")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

_REQUIRED_COLUMNS = ("omega", "omega_metodo")


# ══════════════════════════════════════════════════════════════════════════
# OmegaTable — envoltorio de lectura sobre ω ya calculado (sin recompute)
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class OmegaTable:
    """
    Vista de solo lectura de `warehouse.parquet` para el reparto espacial
    del Stage 7. `table` conserva únicamente las columnas necesarias para
    leer ω (`id_col`, `sector_col`, `omega`, `omega_metodo`); `geometry` es
    la geometría de cada AGEB deduplicada (se repite una vez por sector en
    el warehouse), disponible para que `allocator.py` la reutilice sin
    releer el parquet.
    """
    table: pd.DataFrame
    geometry: pd.Series  # index=id_col, valores=geometrías shapely (objeto plano, sin CRS propio)
    crs: object
    id_col: str = AGEB_ID_COL
    sector_col: str = SECTOR_COL

    def sectors(self) -> list:
        """Sectores con al menos una fila de ω no nulo (i.e. con reparto posible)."""
        valid = self.table.loc[self.table["omega"].notna(), self.sector_col]
        return sorted(valid.unique().tolist())

    def has_sector(self, sector) -> bool:
        """True si `sector` tiene al menos un AGEB con ω conocido."""
        valid = self.table.loc[self.table["omega"].notna(), self.sector_col]
        return sector in valid.values

    def rows_for(self, sector) -> pd.DataFrame:
        """
        Filas (AGEB, sector) con ω no nulo para `sector` — mismas columnas
        que `warehouse.parquet` (sin geometría). No recalcula nada; solo
        filtra lo que `WarehouseBuilder.compute_weights()` ya dejó escrito.
        """
        return self.table[
            (self.table[self.sector_col] == sector) & self.table["omega"].notna()
        ].reset_index(drop=True)

    def omega_for(self, sector) -> pd.Series:
        """ω_{g,s} para `sector`, indexado por AGEB — solo filas con ω conocido."""
        return self.rows_for(sector).set_index(self.id_col)["omega"]

    def n_agebs_sin_omega(self, sector) -> int:
        """
        Número de filas (AGEB, sector) con `omega_metodo == 'sin_datos'`
        (ω no calculable por `WarehouseBuilder`, Stage 5) — ya excluidas
        de `omega_for()`, pero contadas aquí para no ocultar el faltante.
        """
        sub = self.table[self.table[self.sector_col] == sector]
        return int(sub["omega"].isna().sum())


# ══════════════════════════════════════════════════════════════════════════
# Carga — solo lectura del artefacto ya producido por Stage 5
# ══════════════════════════════════════════════════════════════════════════
def load_omega_table(
    parquet_path: str | Path = WAREHOUSE_PARQUET,
    id_col: str = AGEB_ID_COL,
    sector_col: str = SECTOR_COL,
) -> OmegaTable:
    """
    Lee `warehouse.parquet` tal cual y organiza el acceso a ω. No recalcula
    ω, no vuelve a ejecutar el Spatial Join ni el crosswalk — es un
    consumidor puro del artefacto de Stage 5, igual que
    `analytics.diagnostics.load_warehouse()`.
    """
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró warehouse.parquet en '{path}'. Ejecuta "
            "WarehouseBuilder.build()/build_from_gdfs() + to_warehouse_files() (Stage 5) primero."
        )
    gdf = gpd.read_parquet(path)

    missing = [c for c in (id_col, sector_col, *_REQUIRED_COLUMNS) if c not in gdf.columns]
    if missing:
        raise ValueError(
            f"warehouse.parquet no tiene la(s) columna(s) {missing} esperada(s) "
            "por Stage 5 (WarehouseBuilder.compute_weights())."
        )

    table = pd.DataFrame(gdf[[id_col, sector_col, "omega", "omega_metodo"]])

    # Geometría deduplicada por AGEB (se repite una vez por sector_serio en
    # el warehouse) — Serie de objetos plana, sin envoltorio GeoSeries, para
    # que el merge posterior en allocator.py sea explícito y no arrastre CRS
    # implícito a mitad de pipeline.
    geom_dedup = gdf[[id_col, "geometry"]].drop_duplicates(subset=[id_col]).set_index(id_col)["geometry"]
    geometry = pd.Series(geom_dedup.values, index=geom_dedup.index, name="geometry")

    logger.info(
        "Omega table cargada: %s (%d filas, %d AGEBs, %d sectores con ω conocido).",
        path.name, len(table), geometry.shape[0],
        table.loc[table["omega"].notna(), sector_col].nunique(),
    )
    return OmegaTable(table=table, geometry=geometry, crs=gdf.crs, id_col=id_col, sector_col=sector_col)
