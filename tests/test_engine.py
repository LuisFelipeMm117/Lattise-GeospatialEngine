# tests/test_engine.py
"""
Pruebas de spatial.simulation.engine — orquestación end-to-end del SEE
(Incremento 3, "Stage 8C").

Sigue el mismo criterio que tests/test_serio_bridge.py y
tests/test_operator.py:
  1. Un `warehouse.parquet` GENUINO, construido con `WarehouseBuilder`
     sobre AGEBs + DENUE sintéticos y un crosswalk SCIAN→SERIO real
     (Stage 5, cerrado) — nunca mockeado.
  2. Un `graph.gal`/`graph_metadata.json` GENUINO, construido con
     `SpatialGraphBuilder` sobre la MISMA grilla AGEB sintética
     (Spatial Graph Builder, cerrado) — nunca mockeado.
  3. Un `resultado_simulacion` FALSO (mismo patrón `_fake_resultado_simulacion`
     de test_serio_bridge.py) que imita exactamente el dict que produce
     `ModeloEconomico.simular()` (serio/loader.py), sin invocar el modelo
     econométrico real — Stage 8C no depende de SERIO en sí, solo de su
     contrato de salida (`df_detalle` con columnas 'scian'/'delta_X_pesos').

Ninguna prueba reconstruye manualmente W, ni reparte shocks a mano, ni
invoca `propagate()`/`generate_shock_ageb_from_simulacion()` por fuera de
`run_simulation_engine()` — el objetivo es validar la ORQUESTACIÓN, no
reprobar la matemática ya cubierta por test_matrix.py/test_operator.py/
test_serio_bridge.py.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.allocation.allocator import AllocationReport
from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.engine import (
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
    SimulationReport,
    run_simulation_engine,
)
from spatial.simulation.operator import (
    InvalidRhoError,
    PropagationReport,
    ShockAlignmentError,
    ShockVectorReport,
)
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]


# ══════════════════════════════════════════════════════════════════════════
# Fixtures AGEB — idénticas a test_operator.py / test_serio_bridge.py
# ══════════════════════════════════════════════════════════════════════════
def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _make_ageb_grid_raw() -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    return gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")


def _make_denue_raw() -> pd.DataFrame:
    rows = [
        ("A1", "111111", LON0 + 0.003, LAT0 + 0.003, "0 a 5 personas"),
        ("A2", "111111", LON0 + 0.004, LAT0 + 0.004, "6 a 10 personas"),
        ("A3", "111111", LON0 + 0.013, LAT0 + 0.013, "11 a 30 personas"),
        ("A4", "222222", LON0 + 0.003, LAT0 + 0.013, "0 a 5 personas"),
        ("A5", "333333", LON0 + 0.002, LAT0 + 0.001, "rango_desconocido"),
        ("A6", "333333", LON0 + 0.013, LAT0 + 0.003, "rango_desconocido"),
    ]
    return pd.DataFrame(
        rows, columns=["id", "codigo_act", "longitud", "latitud", "per_ocu"]
    ).assign(nom_estab=lambda d: "Estab " + d["id"])


def _crosswalk_table() -> pd.DataFrame:
    return pd.DataFrame({
        "scian_codigo": ["111111", "222222", "333333"],
        "sector_serio": ["SEC001", "SEC002", "SEC003"],
        "notas": ["", "", ""],
    })


@pytest.fixture
def wb() -> WarehouseBuilder:
    return WarehouseBuilder(serio_sectors=REAL_SERIO_SECTORS)


@pytest.fixture
def ageb_gdf() -> gpd.GeoDataFrame:
    return AGEBLoader().normalize(_make_ageb_grid_raw())


@pytest.fixture
def denue_gdf(wb) -> gpd.GeoDataFrame:
    denue_norm = DENUELoader().normalize(_make_denue_raw())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")
    return mapped


@pytest.fixture
def warehouse_parquet_path(tmp_path, wb, ageb_gdf, denue_gdf):
    warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)
    parquet_path, _ = wb.to_warehouse_files(
        warehouse,
        parquet_path=tmp_path / "warehouse.parquet",
        metadata_path=tmp_path / "metadata.json",
    )
    return parquet_path


# ══════════════════════════════════════════════════════════════════════════
# Fixture graph.gal — misma grilla AGEB, vía SpatialGraphBuilder (cerrado)
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def graph_files(tmp_path, ageb_gdf):
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(ageb_gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph,
        gal_path=tmp_path / "graph.gal",
        metadata_path=tmp_path / "graph_metadata.json",
    )
    return gal_path, metadata_path


# ══════════════════════════════════════════════════════════════════════════
# resultado_simulacion — mismo contrato que ModeloEconomico.simular()
# ══════════════════════════════════════════════════════════════════════════
def _fake_resultado_simulacion(sectores, delta_x_pesos) -> dict:
    df_detalle = pd.DataFrame({
        "scian": sectores,
        "delta_X_pesos": delta_x_pesos,
    })
    return {
        "delta_X": np.asarray(delta_x_pesos) * 1e-6,
        "df_detalle": df_detalle,
    }


# ══════════════════════════════════════════════════════════════════════════
# Orquestación end-to-end — feliz camino
# ══════════════════════════════════════════════════════════════════════════
def test_run_simulation_engine_end_to_end(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0]
    )

    gdf_final, report = run_simulation_engine(
        resultado,
        rho=0.3,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    assert isinstance(gdf_final, gpd.GeoDataFrame)
    assert isinstance(report, SimulationReport)

    # Una fila por AGEB de la SpatialMatrix (4 en la grilla 2x2)
    assert len(gdf_final) == 4
    assert set(gdf_final["cvegeo"]) == {"A00", "A01", "A10", "A11"}
    assert {IMPACTO_DIRECTO_COL, IMPACTO_PROPAGADO_COL, IMPACTO_INDIRECTO_COL, "geometry"}.issubset(
        gdf_final.columns
    )
    assert gdf_final.geometry.notna().all()
    assert np.allclose(
        gdf_final[IMPACTO_INDIRECTO_COL],
        gdf_final[IMPACTO_PROPAGADO_COL] - gdf_final[IMPACTO_DIRECTO_COL],
    )

    # Reporte — campos mínimos exigidos
    assert report.rho == pytest.approx(0.3)
    assert report.n_agebs == 4
    assert report.n_sectores == 3
    assert report.shock_total_inicial == pytest.approx(gdf_final[IMPACTO_DIRECTO_COL].sum())
    assert report.shock_total_propagado == pytest.approx(gdf_final[IMPACTO_PROPAGADO_COL].sum())
    assert report.multiplicador_global == pytest.approx(
        report.shock_total_propagado / report.shock_total_inicial
    )
    assert report.tiempo_ejecucion_seg >= 0.0
    assert report.criterio == "queen"

    # Rutas de artefactos utilizados
    assert report.ruta_warehouse_parquet == str(warehouse_parquet_path)
    assert report.ruta_shock_ageb_parquet == str(tmp_path / "shock_ageb.parquet")
    assert report.ruta_graph_gal == str(gal_path)
    assert report.ruta_graph_metadata == str(metadata_path)

    # shock_ageb.parquet debe haberse persistido (Stage 8B lee de disco)
    assert (tmp_path / "shock_ageb.parquet").exists()


def test_run_simulation_engine_rho_zero_is_identity(warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001"], [1_000_000.0])

    gdf_final, report = run_simulation_engine(
        resultado,
        rho=0.0,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    # Con rho=0, (I - rho*W) = I → Y = S exactamente
    assert np.allclose(gdf_final[IMPACTO_PROPAGADO_COL], gdf_final[IMPACTO_DIRECTO_COL])
    assert np.allclose(gdf_final[IMPACTO_INDIRECTO_COL], 0.0)
    assert report.multiplicador_global == pytest.approx(1.0)


def test_run_simulation_engine_embeds_underlying_reports(warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002"], [500_000.0, 100_000.0])

    _, report = run_simulation_engine(
        resultado,
        rho=0.2,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    assert report.allocation_report  # dict no vacío
    assert report.shock_vector_report
    assert report.propagation_report
    assert report.spatial_matrix_report
    assert report.propagation_report["rho"] == pytest.approx(0.2)
    assert report.shock_vector_report["suma_shock_total"] == pytest.approx(
        report.shock_total_inicial
    )


def test_run_simulation_engine_reports_sector_without_spatial_coverage(
    warehouse_parquet_path, graph_files
):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC999"], [1_000_000.0, 500_000.0]
    )

    gdf_final, report = run_simulation_engine(
        resultado,
        rho=0.1,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    assert "SEC999" in report.sectores_sin_cobertura_espacial
    # El monto de SEC999 nunca se distribuyó espacialmente: no infla ΣS
    assert report.shock_total_inicial == pytest.approx(1_000_000.0)
    assert report.n_sectores == 2  # ambos sectores del shock, aunque uno se excluya del reparto


def test_run_simulation_engine_raises_invalidrhoerror_for_rho_out_of_range(
    warehouse_parquet_path, graph_files
):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001"], [1_000_000.0])

    with pytest.raises(InvalidRhoError):
        run_simulation_engine(
            resultado,
            rho=1.5,
            warehouse_parquet_path=warehouse_parquet_path,
            shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
            gal_path=gal_path,
            metadata_path=metadata_path,
        )


def test_run_simulation_engine_raises_filenotfound_on_missing_gal(
    tmp_path, warehouse_parquet_path
):
    resultado = _fake_resultado_simulacion(["SEC001"], [1_000_000.0])

    with pytest.raises(FileNotFoundError):
        run_simulation_engine(
            resultado,
            rho=0.1,
            warehouse_parquet_path=warehouse_parquet_path,
            shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
            gal_path=tmp_path / "no_existe.gal",
            metadata_path=tmp_path / "no_existe_metadata.json",
        )


def test_run_simulation_engine_geometry_matches_ageb_grid(
    warehouse_parquet_path, graph_files, ageb_gdf
):
    gal_path, metadata_path = graph_files
    # Shock en los 3 sectores para garantizar reparto (y por tanto
    # geometria) en los 4 AGEB de la grilla.
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0]
    )

    gdf_final, _report = run_simulation_engine(
        resultado,
        rho=0.25,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    # `ageb_gdf` ya esta normalizado (misma reproyeccion EPSG:6372 que
    # atraviesa warehouse.parquet y shock_ageb.parquet) - geometria de
    # referencia consistente con la que produce el pipeline real.
    expected_bounds = ageb_gdf.set_index("cvegeo").geometry.apply(lambda g: g.bounds)
    for cvegeo in gdf_final["cvegeo"]:
        actual = gdf_final.loc[gdf_final["cvegeo"] == cvegeo, "geometry"].iloc[0]
        assert actual.bounds == pytest.approx(expected_bounds[cvegeo])


# ══════════════════════════════════════════════════════════════════════════
# SimulationReport — to_dict()/to_json() (mismo patrón que el resto del SEW)
# ══════════════════════════════════════════════════════════════════════════
def test_simulation_report_to_dict_and_json_roundtrip(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001"], [1_000_000.0])

    _, report = run_simulation_engine(
        resultado,
        rho=0.1,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    report_dict = report.to_dict()
    assert report_dict["rho"] == pytest.approx(0.1)
    assert isinstance(report_dict["allocation_report"], dict)

    out_path = tmp_path / "simulation_report.json"
    report.to_json(out_path)
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == report_dict


def test_simulation_report_summary_is_readable_string(warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001"], [1_000_000.0])

    _, report = run_simulation_engine(
        resultado,
        rho=0.1,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=gal_path.parent / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )

    text = report.summary()
    assert isinstance(text, str)
    assert "Simulation Engine Report" in text
    assert "multiplicador global" in text