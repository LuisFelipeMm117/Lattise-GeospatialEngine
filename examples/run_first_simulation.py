#!/usr/bin/env python3
# examples/run_first_simulation.py
"""
Primer ejemplo ejecutable del proyecto Lattise-GeospatialEngine.

No es una nueva etapa del pipeline ni un nuevo módulo del SEE — es
únicamente un ejemplo de uso que encadena las APIs públicas YA
EXISTENTES y CERRADAS del proyecto para correr una simulación completa
de principio a fin:

    ModeloEconomico.simular()                              (SERIO)
        -> Scenario.run()                                   (Stage 8D)
        -> run_simulation_engine()                           (Stage 8C — Simulation Engine)
        -> SpatialMatrix.from_gal()                          (Stage 8A)

Como este repositorio no trae datos geoespaciales reales versionados
(`data/warehouse`, `data/graph` están vacíos — ver `.gitignore` /
Explicit Data Contracts, Sección 5), este ejemplo construye el
warehouse y el grafo espacial mínimos necesarios a partir de una
cuadrícula AGEB sintética de 2x2, usando exclusivamente las mismas
APIs públicas y cerradas de los Stages 1-8C que usa la suite de tests
(`AGEBLoader`, `DENUELoader`, `WarehouseBuilder`, `SpatialGraphBuilder`).
El único activo de datos REAL que consume este ejemplo es
`serio/data/` (el modelo SERIO regionalizado, 78 sectores x 32 estados).

No modifica ningún archivo del repositorio: todos los artefactos que
genera (warehouse.parquet, graph.gal, shock_ageb.parquet, el
GeoDataFrame final) se escriben exclusivamente bajo `examples/output/`.

Uso:
    python examples/run_first_simulation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

# ── Permitir ejecución directa sin instalar el paquete ─────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from serio.loader import ModeloEconomico  # SERIO — modelo Leontief regionalizado

from spatial.allocation.serio_bridge import generate_shock_ageb_from_simulacion  # Stage 7 — Bridge
from spatial.graph.network import SpatialGraphBuilder  # Spatial Graph Builder
from spatial.simulation.engine import run_simulation_engine  # Stage 8C — Simulation Engine
from spatial.simulation.matrix import SpatialMatrix  # Stage 8A — SpatialMatrix
from spatial.simulation.scenario import Scenario  # Stage 8D — API de alto nivel
from spatial.warehouse.ageb_loader import AGEBLoader  # Stage 2/3 — AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder  # Stage 5 — WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader  # Stage 2/3 — DENUELoader

# ══════════════════════════════════════════════════════════════════════════
# Parámetros del ejemplo — ESTOS son los únicos "inputs" del usuario
# ══════════════════════════════════════════════════════════════════════════
ESTADO = "QUERETARO"
SECTOR = "111"          # Agricultura (código SCIAN del catálogo SERIO)
MONTO = 1_000_000.0     # shock de demanda final, en pesos MXN
RHO = 0.3               # autocorrelación espacial exógena (SEE-Propagación)

SERIO_DATA_PATH = REPO_ROOT / "serio" / "data"
OUTPUT_DIR = REPO_ROOT / "examples" / "output"

LON0, LAT0, CELL = -99.20, 19.40, 0.01  # cuadrícula sintética (Querétaro, aprox.)


# ══════════════════════════════════════════════════════════════════════════
# 1. Cuadrícula AGEB sintética mínima (2x2, contigüidad queen)
# ══════════════════════════════════════════════════════════════════════════
def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _build_ageb_grid() -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    raw = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    return AGEBLoader().normalize(raw)


# ══════════════════════════════════════════════════════════════════════════
# 2. DENUE sintético + crosswalk hacia el sector SERIO real del ejemplo
# ══════════════════════════════════════════════════════════════════════════
def _build_denue() -> pd.DataFrame:
    rows = [
        ("A1", "111111", LON0 + 0.003, LAT0 + 0.003, "0 a 5 personas"),
        ("A2", "111111", LON0 + 0.004, LAT0 + 0.004, "6 a 10 personas"),
        ("A3", "111111", LON0 + 0.013, LAT0 + 0.013, "11 a 30 personas"),
        ("A4", "111111", LON0 + 0.003, LAT0 + 0.013, "0 a 5 personas"),
    ]
    return pd.DataFrame(
        rows, columns=["id", "codigo_act", "longitud", "latitud", "per_ocu"]
    ).assign(nom_estab=lambda d: "Estab " + d["id"])


def _crosswalk_table() -> pd.DataFrame:
    return pd.DataFrame({
        "scian_codigo": ["111111"],
        "sector_serio": [SECTOR],
        "notas": [""],
    })


# ══════════════════════════════════════════════════════════════════════════
# 3. Construcción de warehouse.parquet (Stage 5, CERRADO)
# ══════════════════════════════════════════════════════════════════════════
def _build_warehouse(ageb_gdf: gpd.GeoDataFrame, output_dir: Path) -> Path:
    wb = WarehouseBuilder(serio_sectors=[SECTOR])
    denue_norm = DENUELoader().normalize(_build_denue())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    denue_mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")

    warehouse = wb.build_from_gdfs(ageb_gdf, denue_mapped)
    parquet_path, _metadata_path = wb.to_warehouse_files(
        warehouse,
        parquet_path=output_dir / "warehouse.parquet",
        metadata_path=output_dir / "warehouse_metadata.json",
    )
    return parquet_path


# ══════════════════════════════════════════════════════════════════════════
# 4. Grafo espacial + SpatialMatrix (Spatial Graph Builder + Stage 8A, CERRADOS)
# ══════════════════════════════════════════════════════════════════════════
def _build_spatial_matrix(ageb_gdf: gpd.GeoDataFrame, output_dir: Path) -> SpatialMatrix:
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(ageb_gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph,
        gal_path=output_dir / "graph.gal",
        metadata_path=output_dir / "graph_metadata.json",
    )
    return SpatialMatrix.from_gal(gal_path, metadata_path)


# ══════════════════════════════════════════════════════════════════════════
# Main — orquestación del ejemplo
# ══════════════════════════════════════════════════════════════════════════
def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("LATTISE — PRIMER EJEMPLO EJECUTABLE (SERIO -> SSD -> SEE)")
    print("=" * 78)

    # ── SERIO — ModeloEconomico real (serio/data) ──────────────────────────
    print(f"\n[1/4] Cargando ModeloEconomico desde '{SERIO_DATA_PATH}'...")
    modelo = ModeloEconomico(str(SERIO_DATA_PATH))
    print(f"      {len(modelo.estados_raw)} estado(s) · {modelo.n} sector(es) SCIAN/SERIO")

    # ── Preparación de artefactos mínimos (warehouse + grafo espacial) ─────
    print("\n[2/4] Construyendo warehouse y grafo espacial sintéticos (2x2)...")
    ageb_gdf = _build_ageb_grid()
    warehouse_parquet = _build_warehouse(ageb_gdf, OUTPUT_DIR)
    sm = _build_spatial_matrix(ageb_gdf, OUTPUT_DIR)
    print(f"      warehouse: {warehouse_parquet}")
    print(f"      SpatialMatrix: {len(sm.ids)} nodo(s), criterio '{sm.criterio}'")

    # ── Stage 8D — Scenario: API de alto nivel (estado, sector, monto, rho) ─
    print("\n[3/4] Ejecutando Scenario (Stage 8D)...")
    escenario = Scenario(estado=ESTADO, sector=SECTOR, monto=MONTO, rho=RHO)
    resultado_escenario = escenario.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=OUTPUT_DIR / "shock_ageb.parquet",
    )
    print()
    print(resultado_escenario.summary())

    # ── Stage 8C — Simulation Engine: GeoDataFrame final ensamblado ────────
    print("\n[4/4] Ejecutando Simulation Engine (Stage 8C) para el GeoDataFrame final...")
    estado_key = modelo.mapa_estados.get(ESTADO, ESTADO)
    sector_idx = modelo.scian_idx[SECTOR]
    resultado_simulacion = modelo.simular(estado_key, sector_idx, MONTO)

    gdf_final, engine_report = run_simulation_engine(
        resultado_simulacion,
        rho=RHO,
        warehouse_parquet_path=warehouse_parquet,
        shock_ageb_output_path=OUTPUT_DIR / "shock_ageb.parquet",
        gal_path=OUTPUT_DIR / "graph.gal",
        metadata_path=OUTPUT_DIR / "graph_metadata.json",
    )
    print()
    print(engine_report.summary())

    # ── Persistencia del GeoDataFrame resultante ────────────────────────────
    output_geoparquet = OUTPUT_DIR / "resultado_simulacion.parquet"
    gdf_final.to_parquet(output_geoparquet)

    output_geojson = OUTPUT_DIR / "resultado_simulacion.geojson"
    gdf_final.to_file(output_geojson, driver="GeoJSON")

    engine_report.to_json(OUTPUT_DIR / "simulation_report.json")
    resultado_escenario.to_json(OUTPUT_DIR / "scenario_report.json")

    print("\n" + "=" * 78)
    print("RESUMEN FINAL")
    print("=" * 78)
    print(f"Estado             : {ESTADO} ({estado_key})")
    print(f"Sector             : {SECTOR} — {modelo.sector_names[SECTOR]}")
    print(f"Monto del shock    : ${MONTO:,.0f} MXN")
    print(f"Rho                : {RHO}")
    print(f"AGEBs propagados   : {len(gdf_final)}")
    print(f"Choque directo (S) : {gdf_final['shock_directo'].sum():,.4f}")
    print(f"Impacto propagado (Y): {gdf_final['impacto_propagado'].sum():,.4f}")
    print("\nArchivos generados:")
    for path in [
        warehouse_parquet,
        OUTPUT_DIR / "graph.gal",
        OUTPUT_DIR / "shock_ageb.parquet",
        output_geoparquet,
        output_geojson,
        OUTPUT_DIR / "simulation_report.json",
        OUTPUT_DIR / "scenario_report.json",
    ]:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
