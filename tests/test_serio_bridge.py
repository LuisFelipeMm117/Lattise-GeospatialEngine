from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.allocation.allocator import AllocationReport, generate_shock_ageb
from spatial.allocation.serio_bridge import (
    generate_shock_ageb_from_simulacion,
    shock_from_resultado_simulacion,
)
from spatial.allocation.weights import load_omega_table
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]


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
def real_warehouse_parquet(tmp_path, wb, ageb_gdf, denue_gdf):
    warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)
    parquet_path, _ = wb.to_warehouse_files(
        warehouse,
        parquet_path=tmp_path / "warehouse.parquet",
        metadata_path=tmp_path / "metadata.json",
    )
    return parquet_path


def _fake_resultado_simulacion(sectores, delta_x_pesos) -> dict:
    df_detalle = pd.DataFrame({
        "scian": sectores,
        "delta_X_pesos": delta_x_pesos,
    })
    return {
        "delta_X": np.asarray(delta_x_pesos) * 1e-6,
        "df_detalle": df_detalle,
    }


def test_shock_from_resultado_simulacion_builds_series():
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002"], [1_000_000.0, -200_000.0])
    shock = shock_from_resultado_simulacion(resultado)
    assert isinstance(shock, pd.Series)
    assert shock["SEC001"] == pytest.approx(1_000_000.0)
    assert shock["SEC002"] == pytest.approx(-200_000.0)


def test_shock_from_resultado_simulacion_raises_without_df_detalle():
    with pytest.raises(ValueError):
        shock_from_resultado_simulacion({"delta_X": np.array([1.0])})


def test_shock_from_resultado_simulacion_raises_on_missing_columns():
    resultado = {"df_detalle": pd.DataFrame({"otra_col": [1, 2]})}
    with pytest.raises(ValueError):
        shock_from_resultado_simulacion(resultado)


def test_shock_from_resultado_simulacion_raises_on_duplicate_sectors():
    resultado = _fake_resultado_simulacion(["SEC001", "SEC001"], [100.0, 50.0])
    with pytest.raises(ValueError):
        shock_from_resultado_simulacion(resultado)


def test_shock_from_resultado_simulacion_coerces_sector_dtype_to_str():
    resultado = _fake_resultado_simulacion([111, 222], [10.0, 20.0])
    shock = shock_from_resultado_simulacion(resultado)
    assert list(shock.index) == ["111", "222"]


def test_pipeline_end_to_end_matches_manual_shock(real_warehouse_parquet):
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0]
    )

    gdf_bridge, report_bridge = generate_shock_ageb_from_simulacion(
        resultado, parquet_path=real_warehouse_parquet, write=False
    )
    gdf_manual, report_manual = generate_shock_ageb(
        {"SEC001": 1_000_000.0, "SEC002": 200_000.0, "SEC003": 50_000.0},
        parquet_path=real_warehouse_parquet,
        write=False,
    )

    pd.testing.assert_frame_equal(
        gdf_bridge.sort_values(["sector_serio", "cvegeo"]).reset_index(drop=True),
        gdf_manual.sort_values(["sector_serio", "cvegeo"]).reset_index(drop=True),
    )
    assert report_bridge.to_dict() == report_manual.to_dict()


def test_pipeline_no_mass_loss_for_covered_sectors(real_warehouse_parquet):
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002"], [1_000_000.0, 300_000.0])
    gdf, report = generate_shock_ageb_from_simulacion(
        resultado, parquet_path=real_warehouse_parquet, write=False
    )

    assert report.sectores_sin_cobertura_espacial == []
    for sector, monto in [("SEC001", 1_000_000.0), ("SEC002", 300_000.0)]:
        total = gdf.loc[gdf["sector_serio"] == sector, "shock_ageb"].sum()
        assert total == pytest.approx(monto)
        assert report.total_shock_distribuido[sector] == pytest.approx(monto)


def test_pipeline_reports_sector_without_spatial_coverage_explicitly(real_warehouse_parquet):
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC999"], [1_000_000.0, 500_000.0]
    )
    gdf, report = generate_shock_ageb_from_simulacion(
        resultado, parquet_path=real_warehouse_parquet, write=False
    )

    assert "SEC999" in report.sectores_sin_cobertura_espacial
    assert set(gdf["sector_serio"]) == {"SEC001"}
    assert report.n_sectores_shock == 2
    assert report.n_sectores_distribuidos == 1


def test_pipeline_writes_parquet_when_write_true(tmp_path, real_warehouse_parquet):
    resultado = _fake_resultado_simulacion(["SEC001"], [1_000_000.0])
    output_path = tmp_path / "shock_ageb.parquet"

    gdf, report = generate_shock_ageb_from_simulacion(
        resultado,
        parquet_path=real_warehouse_parquet,
        output_path=output_path,
        write=True,
    )

    assert output_path.exists()
    on_disk = gpd.read_parquet(output_path)
    assert isinstance(on_disk, gpd.GeoDataFrame)
    assert "geometry" in on_disk.columns
    assert on_disk.geometry.notna().all()
    assert len(on_disk) == len(gdf)
    assert isinstance(report, AllocationReport)


def test_pipeline_result_is_valid_geodataframe_with_matching_sectors(real_warehouse_parquet):
    omega_table = load_omega_table(real_warehouse_parquet)
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 80_000.0]
    )

    gdf, report = generate_shock_ageb_from_simulacion(
        resultado, parquet_path=real_warehouse_parquet, write=False
    )

    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf.crs == omega_table.crs
    assert gdf.geometry.notna().all()
    assert set(gdf["sector_serio"]).issubset(set(REAL_SERIO_SECTORS))
    assert report.n_sectores_shock == 3
    assert report.n_sectores_distribuidos == 3
    assert report.sectores_sin_cobertura_espacial == []
    for sector in ["SEC001", "SEC002", "SEC003"]:
        assert report.omega_sum_by_sector[sector] == pytest.approx(1.0, abs=1e-6) or \
            sector in report.sectores_omega_no_normalizado