# examples/build_real_pipeline.py
"""
Construye los artefactos reales del SEW Engine (Warehouse + Spatial Graph)
a partir de los insumos crudos de INEGI para Querétaro, reutilizando
exclusivamente las APIs públicas ya existentes:

    spatial.warehouse.builder.WarehouseBuilder
    spatial.graph.network.SpatialGraphBuilder

No se crean clases nuevas, no se modifican módulos existentes, no se
duplica lógica de negocio. Los únicos pasos "propios" de este script son
la extracción de los archivos requeridos desde los ZIP de INEGI
(zipfile de la librería estándar) hacia una carpeta temporal, porque los
loaders del motor (`AGEBLoader`, `DENUELoader`) esperan una ruta de
archivo existente en disco.

Insumos:
    data/raw/inegi/marco_geoestadistico/22_queretaro.zip
        -> conjunto_de_datos/22a.shp (+ .dbf/.shx/.prj/.cpg)
    data/raw/inegi/denue/denue_22_csv.zip
        -> conjunto_de_datos/denue_inegi_22_.csv

Salidas:
    data/warehouse/warehouse.parquet
    data/warehouse/metadata.json
    data/graph/graph.gal
    data/graph/graph_metadata.json
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spatial.config import (
    AGEB_ID_COL,
    CROSSWALK_COMPILED_CSV,
    GRAPH_GAL_PATH,
    GRAPH_METADATA_JSON,
    RAW_DIR,
    SERIO_SECTORES_CSV,
    WAREHOUSE_METADATA,
    WAREHOUSE_PARQUET,
)
from spatial.graph.network import SpatialGraphBuilder
from spatial.warehouse.builder import SECTOR_COL, WarehouseBuilder

MARCO_ZIP = RAW_DIR / "inegi" / "marco_geoestadistico" / "22_queretaro.zip"
DENUE_ZIP = RAW_DIR / "inegi" / "denue" / "denue_22_csv.zip"

AGEB_SHP_MEMBER_PREFIX = "conjunto_de_datos/22a."
DENUE_CSV_MEMBER = "conjunto_de_datos/denue_inegi_22_.csv"


def _extract_ageb_shapefile(zip_path: Path, dest_dir: Path) -> Path:
    """Extrae 22a.shp y sus componentes (.dbf/.shx/.prj/.cpg) del ZIP."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.startswith(AGEB_SHP_MEMBER_PREFIX)]
        if not any(m.endswith(".shp") for m in members):
            raise FileNotFoundError(
                f"No se encontró '{AGEB_SHP_MEMBER_PREFIX}*.shp' dentro de {zip_path}"
            )
        for member in members:
            zf.extract(member, dest_dir)
    return dest_dir / "conjunto_de_datos" / "22a.shp"


def _extract_denue_csv(zip_path: Path, dest_dir: Path) -> Path:
    """Extrae el CSV del DENUE del ZIP."""
    with zipfile.ZipFile(zip_path) as zf:
        if DENUE_CSV_MEMBER not in zf.namelist():
            raise FileNotFoundError(
                f"No se encontró '{DENUE_CSV_MEMBER}' dentro de {zip_path}"
            )
        zf.extract(DENUE_CSV_MEMBER, dest_dir)
    return dest_dir / DENUE_CSV_MEMBER


def main() -> None:
    t0 = time.perf_counter()

    for zp in (MARCO_ZIP, DENUE_ZIP):
        if not zp.exists():
            raise FileNotFoundError(f"No se encontró el insumo INEGI esperado: {zp}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="sew_real_pipeline_"))
    try:
        ageb_shp_path = _extract_ageb_shapefile(MARCO_ZIP, tmp_dir / "marco_geoestadistico")
        denue_csv_path = _extract_denue_csv(DENUE_ZIP, tmp_dir / "denue")

        serio_sectors = pd.read_csv(SERIO_SECTORES_CSV, dtype=str)["scian"].tolist()

        wb = WarehouseBuilder(serio_sectors=serio_sectors, id_col=AGEB_ID_COL)

        ageb_gdf = wb.load_ageb(ageb_shp_path)
        denue_gdf = wb.load_denue(denue_csv_path)
        denue_gdf, unmapped_codes, cw_report = wb.apply_crosswalk(
            denue_gdf, crosswalk_path=CROSSWALK_COMPILED_CSV
        )

        warehouse_gdf = wb.build_from_gdfs(ageb_gdf, denue_gdf)

        print(wb.join_report.summary())
        print(wb.integrity_report.summary())

        warehouse_parquet_path, warehouse_metadata_path = wb.to_warehouse_files(
            warehouse_gdf,
            parquet_path=WAREHOUSE_PARQUET,
            metadata_path=WAREHOUSE_METADATA,
        )

        graph_builder = SpatialGraphBuilder(id_col=AGEB_ID_COL, criterio="queen")
        spatial_graph = graph_builder.build(ageb_gdf)
        print(spatial_graph.report.summary())

        graph_gal_path, graph_metadata_path = graph_builder.to_graph_files(
            spatial_graph,
            gal_path=GRAPH_GAL_PATH,
            metadata_path=GRAPH_METADATA_JSON,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed = time.perf_counter() - t0

    n_agebs = int(ageb_gdf[AGEB_ID_COL].nunique())
    n_establecimientos = int(len(denue_gdf))
    sectores_presentes = sorted(warehouse_gdf[SECTOR_COL].dropna().astype(str).unique().tolist())

    print("\n" + "=" * 70)
    print("RESUMEN — SEW Real Pipeline (Querétaro)")
    print("=" * 70)
    print(f"AGEBs procesados:            {n_agebs}")
    print(f"Establecimientos DENUE:      {n_establecimientos}")
    print(f"Sectores SERIO presentes:    {len(sectores_presentes)} -> {sectores_presentes}")
    print(f"Códigos SCIAN sin mapeo:     {len(unmapped_codes)}")
    print(f"Tiempo total:                {elapsed:.2f} s")
    print("-" * 70)
    print(f"Warehouse parquet:           {warehouse_parquet_path}")
    print(f"Warehouse metadata:          {warehouse_metadata_path}")
    print(f"Graph GAL:                   {graph_gal_path}")
    print(f"Graph metadata:              {graph_metadata_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()