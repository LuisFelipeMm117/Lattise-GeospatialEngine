# tests/test_scenario.py
"""
Pruebas de spatial.simulation.scenario — API de alto nivel del SEE
(Stage 8D).

Sigue el mismo criterio que tests/test_operator.py y
tests/test_serio_bridge.py:
  1. `ModeloEconomico` REAL (`serio.loader`), cargado desde el activo de
     datos real del repositorio (`serio/data/`) — nunca mockeado.
  2. Fixtures AGEB sintéticas (grid 2x2) para construir un warehouse
     real vía `WarehouseBuilder` y una `SpatialMatrix` real vía
     `SpatialGraphBuilder` + `SpatialMatrix.from_gal()` — mismo patrón
     que tests/test_serio_bridge.py y tests/test_operator.py.
  3. El crosswalk sintético mapea actividades DENUE a códigos SCIAN
     SERIO reales (tomados de `modelo.sectores`), para que
     `Scenario.run()` ejercite el pipeline end-to-end con un
     `ModeloEconomico` genuino.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.allocation.serio_bridge import generate_shock_ageb_from_simulacion
from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.matrix import SpatialMatrix
from spatial.simulation.educational_report import build_educational_report
from spatial.simulation.operator import ShockAlignmentError
from spatial.simulation.scenario import (
    Scenario,
    ScenarioConfigError,
    ScenarioReport,
    ScenarioResult,
)
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

from serio.loader import ModeloEconomico

LON0, LAT0, CELL = -99.20, 19.40, 0.01
SERIO_DATA_PATH = Path(__file__).resolve().parent.parent / "serio" / "data"

# Códigos SCIAN reales del catálogo SERIO (serio/data/meta.json),
# usados también como categorías del crosswalk/warehouse sintético.
SECTOR_A = "111"   # Agricultura
SECTOR_B = "112"   # Cría y explotación de animales
SECTOR_C = "113"   # Aprovechamiento forestal
ESTADO_KEY = "QUERETARO"


# ══════════════════════════════════════════════════════════════════════════
# ModeloEconomico real — cargado desde el activo de datos del repositorio
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def modelo() -> ModeloEconomico:
    return ModeloEconomico(str(SERIO_DATA_PATH))


# ══════════════════════════════════════════════════════════════════════════
# Fixtures AGEB / warehouse / SpatialMatrix — mismo patrón que
# tests/test_serio_bridge.py y tests/test_operator.py
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
        "sector_serio": [SECTOR_A, SECTOR_B, SECTOR_C],
        "notas": ["", "", ""],
    })


@pytest.fixture(scope="module")
def ageb_gdf() -> gpd.GeoDataFrame:
    return AGEBLoader().normalize(_make_ageb_grid_raw())


@pytest.fixture(scope="module")
def wb() -> WarehouseBuilder:
    return WarehouseBuilder(serio_sectors=[SECTOR_A, SECTOR_B, SECTOR_C])


@pytest.fixture(scope="module")
def denue_gdf(wb) -> gpd.GeoDataFrame:
    denue_norm = DENUELoader().normalize(_make_denue_raw())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")
    return mapped


@pytest.fixture
def warehouse_parquet(tmp_path, wb, ageb_gdf, denue_gdf) -> Path:
    warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)
    parquet_path, _ = wb.to_warehouse_files(
        warehouse,
        parquet_path=tmp_path / "warehouse.parquet",
        metadata_path=tmp_path / "metadata.json",
    )
    return parquet_path


@pytest.fixture
def sm(tmp_path, ageb_gdf) -> SpatialMatrix:
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(ageb_gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph,
        gal_path=tmp_path / "graph.gal",
        metadata_path=tmp_path / "graph_metadata.json",
    )
    return SpatialMatrix.from_gal(gal_path, metadata_path)


# ══════════════════════════════════════════════════════════════════════════
# Scenario — construcción mínima (solo estado, sector, monto, rho)
# ══════════════════════════════════════════════════════════════════════════
def test_scenario_is_constructed_with_exactly_four_user_fields():
    field_names = {f for f in Scenario.__dataclass_fields__}
    assert field_names == {"estado", "sector", "monto", "rho"}


def test_scenario_stores_raw_user_inputs_unchanged():
    sc = Scenario(estado="Queretaro", sector=SECTOR_A, monto=1_000_000.0, rho=0.3)
    assert sc.estado == "Queretaro"
    assert sc.sector == SECTOR_A
    assert sc.monto == 1_000_000.0
    assert sc.rho == 0.3


# ══════════════════════════════════════════════════════════════════════════
# Resolución explícita de estado / sector
# ══════════════════════════════════════════════════════════════════════════
def test_run_accepts_readable_state_name(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado="Queretaro", sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert result.report.estado_key == ESTADO_KEY


def test_run_accepts_internal_folder_key(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert result.report.estado_key == ESTADO_KEY


def test_run_raises_scenarioconfigerror_on_unknown_estado(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado="Narnia", sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    with pytest.raises(ScenarioConfigError):
        sc.run(
            modelo, sm,
            warehouse_parquet=warehouse_parquet,
            shock_ageb_output=tmp_path / "shock_ageb.parquet",
        )


def test_run_raises_scenarioconfigerror_on_unknown_sector(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector="999999", monto=1_000_000.0, rho=0.0)
    with pytest.raises(ScenarioConfigError):
        sc.run(
            modelo, sm,
            warehouse_parquet=warehouse_parquet,
            shock_ageb_output=tmp_path / "shock_ageb.parquet",
        )


def test_run_reports_correct_sector_idx_and_nombre(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_B, monto=500_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert result.report.sector_idx == modelo.scian_idx[SECTOR_B]
    assert result.report.sector_nombre == modelo.sector_names[SECTOR_B]


# ══════════════════════════════════════════════════════════════════════════
# Pipeline end-to-end — SERIO -> SSD -> shock_ageb.parquet -> propagación
# ══════════════════════════════════════════════════════════════════════════
def test_run_delta_x_matches_direct_modeloeconomico_simular(modelo, sm, warehouse_parquet, tmp_path):
    sector_idx = modelo.scian_idx[SECTOR_A]
    esperado = modelo.simular(ESTADO_KEY, sector_idx, 1_000_000.0)

    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )

    assert result.report.delta_X_total_pesos == pytest.approx(esperado["delta_X_total_pesos"])
    assert result.report.delta_VA_total_pesos == pytest.approx(esperado["delta_VA_total_pesos"])
    assert result.report.delta_E_total == pytest.approx(esperado["delta_E_total"])
    assert result.report.mult_produccion == pytest.approx(esperado["mult_produccion"])


def test_run_shock_ageb_matches_serio_bridge_directly(modelo, sm, warehouse_parquet, tmp_path):
    sector_idx = modelo.scian_idx[SECTOR_A]
    resultado_simulacion = modelo.simular(ESTADO_KEY, sector_idx, 1_000_000.0)
    expected_gdf, expected_report = generate_shock_ageb_from_simulacion(
        resultado_simulacion, parquet_path=warehouse_parquet, write=False,
    )

    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )

    pd.testing.assert_frame_equal(
        result.shock_gdf.sort_values(["sector_serio", "cvegeo"]).reset_index(drop=True),
        expected_gdf.sort_values(["sector_serio", "cvegeo"]).reset_index(drop=True),
    )
    assert result.allocation_report.to_dict() == expected_report.to_dict()


def test_run_writes_shock_ageb_parquet_to_configured_output(modelo, sm, warehouse_parquet, tmp_path):
    output_path = tmp_path / "custom_shock_ageb.parquet"
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=output_path,
    )
    assert output_path.exists()


def test_run_propagation_identity_when_rho_is_zero(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    np.testing.assert_allclose(result.Y, result.S, atol=1e-10)
    assert result.propagation_report.rho == pytest.approx(0.0)


def test_run_propagation_diffuses_more_at_higher_rho(modelo, sm, warehouse_parquet, tmp_path):
    base = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0).run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb_rho0.parquet",
    )
    diffused = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.3).run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb_rho3.parquet",
    )
    idx_a01 = sm.index_of("A01")  # vecino de A00, sin shock directo propio
    assert diffused.Y[idx_a01] > base.Y[idx_a01]


def test_run_s_series_and_y_series_indexed_by_cvegeo(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.2)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    s_series = result.s_series()
    y_series = result.y_series()
    assert list(s_series.index) == sm.ids
    assert list(y_series.index) == sm.ids
    assert s_series.loc["A00"] == pytest.approx(result.S[sm.index_of("A00")])
    assert y_series.loc["A00"] == pytest.approx(result.Y[sm.index_of("A00")])


def test_run_sector_activo_en_estado_flag_reflects_va_r(modelo, sm, warehouse_parquet, tmp_path):
    sector_idx = modelo.scian_idx[SECTOR_A]
    d_estado = modelo._load_estado(ESTADO_KEY)
    esperado_activo = bool(d_estado["VA_r"][sector_idx] > 0)

    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert result.report.sector_activo_en_estado == esperado_activo


def test_run_reports_sector_without_spatial_coverage_explicitly(modelo, sm, warehouse_parquet, tmp_path):
    # Sector SCIAN real del catálogo SERIO, pero sin ninguna fila de omega
    # en el warehouse sintético (solo SECTOR_A/B/C están cubiertos).
    sector_sin_cobertura = "115"
    sc = Scenario(estado=ESTADO_KEY, sector=sector_sin_cobertura, monto=100_000.0, rho=0.0)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert sector_sin_cobertura in result.report.sectores_sin_cobertura_espacial
    assert sector_sin_cobertura not in set(result.shock_gdf["sector_serio"])


def test_run_raises_shockalignmenterror_when_strict_and_matrix_missing_agebs(
    modelo, warehouse_parquet, tmp_path,
):
    # SpatialMatrix construida sobre un universo de AGEBs más pequeño que
    # el warehouse (solo A00), para forzar una inconsistencia real S vs W.
    small_gdf = _make_ageb_grid_raw()
    small_gdf = small_gdf[small_gdf["cvegeo"] == "A00"].reset_index(drop=True)
    small_gdf = AGEBLoader().normalize(small_gdf)

    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(small_gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph, gal_path=tmp_path / "small_graph.gal", metadata_path=tmp_path / "small_graph_metadata.json",
    )
    small_sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.0)
    with pytest.raises(ShockAlignmentError):
        sc.run(
            modelo, small_sm,
            warehouse_parquet=warehouse_parquet,
            shock_ageb_output=tmp_path / "shock_ageb.parquet",
        )


# ══════════════════════════════════════════════════════════════════════════
# ScenarioReport / ScenarioResult — to_dict()/to_json()/summary()
# ══════════════════════════════════════════════════════════════════════════
def test_scenario_report_to_dict_and_json_roundtrip(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.1)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert isinstance(result.report, ScenarioReport)
    d = result.report.to_dict()
    assert d["estado_key"] == ESTADO_KEY
    assert d["rho"] == pytest.approx(0.1)

    json_path = tmp_path / "scenario_report.json"
    result.report.to_json(json_path)
    assert json_path.exists()

    import json as _json
    on_disk = _json.loads(json_path.read_text(encoding="utf-8"))
    assert on_disk == d


def test_scenario_result_delegates_to_dict_json_summary_to_report(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.1)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    assert isinstance(result, ScenarioResult)
    assert result.to_dict() == result.report.to_dict()
    assert result.summary() == result.report.summary()

    json_path = tmp_path / "scenario_result.json"
    result.to_json(json_path)
    assert json_path.exists()


def test_scenario_report_summary_is_nonempty_string(modelo, sm, warehouse_parquet, tmp_path):
    sc = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.1)
    result = sc.run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    summary = result.report.summary()
    assert isinstance(summary, str)
    assert ESTADO_KEY in summary
    assert SECTOR_A in summary


def test_educational_report_records_provenance_coverage_warning_and_ranking(
    modelo, sm, warehouse_parquet, tmp_path,
):
    """El reporte educativo solo lee ScenarioResult y conserva su trazabilidad."""
    result = Scenario(estado=ESTADO_KEY, sector=SECTOR_A, monto=1_000_000.0, rho=0.2).run(
        modelo, sm,
        warehouse_parquet=warehouse_parquet,
        shock_ageb_output=tmp_path / "shock_ageb.parquet",
    )
    warehouse_metadata = tmp_path / "metadata.json"
    graph_gal = tmp_path / "graph.gal"
    graph_metadata = tmp_path / "graph_metadata.json"
    crosswalk = tmp_path / "crosswalk.csv"
    crosswalk_report = tmp_path / "crosswalk_report.json"
    graph_gal.write_text("fixture", encoding="utf-8")
    graph_metadata.write_text('{"criterio": "queen"}', encoding="utf-8")
    crosswalk.write_text("scian_codigo,sector_serio\n111111,111\n", encoding="utf-8")
    crosswalk_report.write_text("{}", encoding="utf-8")

    educational = build_educational_report(
        result,
        rho_method="manual",
        warehouse_parquet=warehouse_parquet,
        warehouse_metadata=warehouse_metadata,
        graph_gal=graph_gal,
        graph_metadata=graph_metadata,
        crosswalk_path=crosswalk,
        crosswalk_report=crosswalk_report,
        serio_data_dir=SERIO_DATA_PATH,
        bundle_sha256="a" * 64,
        top_n=2,
    )

    assert educational.schema_version == "1.0"
    assert educational.parameters["metodo_rho"] == "manual"
    assert educational.parameters["sectores"] == [{"codigo": SECTOR_A, "monto_pesos": 1_000_000.0}]
    assert educational.artifacts["bundle"]["sha256"] == "a" * 64
    assert educational.artifacts["warehouse"]["dataset"]["sha256"]
    assert educational.spatial_coverage["n_agebs_matrix"] == len(sm.ids)
    assert len(educational.ranking) == 2
    assert "no una estimación causal" in educational.methodological_warning

    output = tmp_path / "educational_report.json"
    educational.to_json(output)
    assert json.loads(output.read_text(encoding="utf-8"))["scenario_fingerprint"] == educational.scenario_fingerprint

    delegated = result.educational_report(
        warehouse_parquet=warehouse_parquet,
        warehouse_metadata=warehouse_metadata,
        graph_gal=graph_gal,
        graph_metadata=graph_metadata,
        crosswalk_path=crosswalk,
        crosswalk_report=crosswalk_report,
        serio_data_dir=SERIO_DATA_PATH,
        bundle_sha256="a" * 64,
        top_n=2,
    )
    assert delegated.scenario_fingerprint == educational.scenario_fingerprint
