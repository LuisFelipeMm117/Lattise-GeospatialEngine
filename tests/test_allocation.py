# tests/test_allocation.py
"""
Pruebas de Allocation / Spatial Shock Distributor (Stage 7).

Dos escenarios, siguiendo el mismo criterio que tests/test_diagnostics.py:

  1. Un warehouse SINTÉTICO construido directamente (sin pasar por
     WarehouseBuilder) para ejercer con precisión los casos de borde de
     Stage 7: sectores sin ninguna fila con ω válido, AGEBs 'sin_datos'
     mezclados con AGEBs válidos, y ω que no suma 1.
  2. El MISMO grid AGEB/DENUE sintético de tests/test_builder.py y
     tests/test_diagnostics.py, corrido a través de WarehouseBuilder real
     (Stage 5), para confirmar que allocate_shock()/generate_shock_ageb()
     funcionan sobre un warehouse.parquet genuino — sin recalcular Spatial
     Join, Crosswalk ni ω en ningún punto de este archivo.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.allocation.allocator import (
    AllocationReport,
    allocate_shock,
    generate_shock_ageb,
    normalize_shock_vector,
)
from spatial.allocation.weights import OmegaTable, load_omega_table
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01


# ══════════════════════════════════════════════════════════════════════════
# Escenario 1 — warehouse sintético, construido directamente (casos de borde)
# ══════════════════════════════════════════════════════════════════════════
def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _make_synthetic_warehouse_gdf() -> gpd.GeoDataFrame:
    """
    Sectores:
      SEC001 — A00 (ω=0.6, empleo), A01 (ω=0.4, empleo) → totalmente válido, suma 1.0
      SEC002 — A00 (ω=1.0, establecimientos), A10 (ω=NaN, sin_datos) → parcialmente válido
      SEC003 — A11 (ω=NaN, sin_datos) → SIN ningún AGEB con ω calculable
      SEC004 — A00 (ω=0.5, empleo) únicamente → ω no suma 1 (dato deliberadamente no normalizado)
    """
    rows = [
        ("A00", "SEC001", 3, 30.0, 0, 0.6, "empleo"),
        ("A01", "SEC001", 2, 20.0, 0, 0.4, "empleo"),
        ("A00", "SEC002", 1, 0.0, 1, 1.0, "establecimientos"),
        ("A10", "SEC002", 1, 0.0, 1, np.nan, "sin_datos"),
        ("A11", "SEC003", 1, 0.0, 1, np.nan, "sin_datos"),
        ("A00", "SEC004", 1, 10.0, 0, 0.5, "empleo"),
    ]
    df = pd.DataFrame(
        rows,
        columns=["cvegeo", "sector_serio", "n_establecimientos", "empleo_total", "n_empleo_faltante", "omega", "omega_metodo"],
    )
    geoms = {"A00": _square(0, 0), "A01": _square(0, 1), "A10": _square(1, 0), "A11": _square(1, 1)}
    df["geometry"] = df["cvegeo"].map(geoms)
    return gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:6372")


@pytest.fixture
def synthetic_parquet(tmp_path):
    gdf = _make_synthetic_warehouse_gdf()
    path = tmp_path / "warehouse.parquet"
    gdf.to_parquet(path)
    return path


@pytest.fixture
def omega_table(synthetic_parquet) -> OmegaTable:
    return load_omega_table(synthetic_parquet)


# ── weights.py — OmegaTable / load_omega_table ─────────────────────────────
def test_load_omega_table_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_omega_table(tmp_path / "no_existe.parquet")


def test_load_omega_table_raises_on_missing_columns(tmp_path):
    incomplete = gpd.GeoDataFrame(
        {"cvegeo": ["A00"], "sector_serio": ["SEC001"]},
        geometry=[_square(0, 0)], crs="EPSG:6372",
    )
    path = tmp_path / "warehouse.parquet"
    incomplete.to_parquet(path)
    with pytest.raises(ValueError):
        load_omega_table(path)


def test_omega_table_sectors_excludes_sectors_without_any_valid_omega(omega_table):
    # SEC003 no tiene ninguna fila con ω no nulo → excluido de sectors()
    assert set(omega_table.sectors()) == {"SEC001", "SEC002", "SEC004"}


def test_omega_table_has_sector(omega_table):
    assert omega_table.has_sector("SEC001") is True
    assert omega_table.has_sector("SEC003") is False
    assert omega_table.has_sector("SEC999") is False


def test_omega_table_omega_for_excludes_sin_datos_rows(omega_table):
    omega_sec002 = omega_table.omega_for("SEC002")
    assert list(omega_sec002.index) == ["A00"]
    assert omega_sec002.loc["A00"] == pytest.approx(1.0)


def test_omega_table_n_agebs_sin_omega(omega_table):
    assert omega_table.n_agebs_sin_omega("SEC001") == 0
    assert omega_table.n_agebs_sin_omega("SEC002") == 1
    assert omega_table.n_agebs_sin_omega("SEC003") == 1


def test_omega_table_geometry_is_deduplicated_per_ageb(omega_table):
    # A00 aparece en 3 filas del warehouse (SEC001, SEC002, SEC004) pero
    # geometry no debe duplicarse.
    assert omega_table.geometry.index.is_unique
    assert set(omega_table.geometry.index) == {"A00", "A01", "A10", "A11"}


# ── normalize_shock_vector() — puente agnóstico a cualquier modelo IO ──────
def test_normalize_shock_vector_builds_series_from_positional_arrays():
    shock = normalize_shock_vector(["SEC001", "SEC002"], np.array([1000.0, -500.0]))
    assert isinstance(shock, pd.Series)
    assert shock["SEC001"] == 1000.0
    assert shock["SEC002"] == -500.0


def test_normalize_shock_vector_raises_on_length_mismatch():
    with pytest.raises(ValueError):
        normalize_shock_vector(["SEC001", "SEC002"], [1000.0])


# ── allocate_shock() — formatos de entrada aceptados ───────────────────────
def test_allocate_shock_accepts_dict(omega_table):
    out, report = allocate_shock({"SEC001": 1000.0}, omega_table)
    assert set(out["cvegeo"]) == {"A00", "A01"}
    assert out.loc[out["cvegeo"] == "A00", "shock_ageb"].iloc[0] == pytest.approx(600.0)
    assert out.loc[out["cvegeo"] == "A01", "shock_ageb"].iloc[0] == pytest.approx(400.0)


def test_allocate_shock_accepts_series(omega_table):
    shock = pd.Series({"SEC001": 1000.0})
    out, _ = allocate_shock(shock, omega_table)
    assert out["shock_ageb"].sum() == pytest.approx(1000.0)


def test_allocate_shock_accepts_dataframe(omega_table):
    shock_df = pd.DataFrame({"sector_serio": ["SEC001"], "delta_x": [1000.0]})
    out, _ = allocate_shock(shock_df, omega_table)
    assert out["shock_ageb"].sum() == pytest.approx(1000.0)


def test_allocate_shock_dataframe_raises_on_missing_columns(omega_table):
    bad_df = pd.DataFrame({"sector": ["SEC001"], "monto": [1000.0]})
    with pytest.raises(ValueError):
        allocate_shock(bad_df, omega_table)


def test_allocate_shock_dataframe_raises_on_duplicate_sectors(omega_table):
    dup_df = pd.DataFrame({"sector_serio": ["SEC001", "SEC001"], "delta_x": [1000.0, 500.0]})
    with pytest.raises(ValueError):
        allocate_shock(dup_df, omega_table)


def test_allocate_shock_raises_on_unsupported_type(omega_table):
    with pytest.raises(TypeError):
        allocate_shock([("SEC001", 1000.0)], omega_table)


# ── allocate_shock() — reparto, cobertura y reporte ─────────────────────────
def test_allocate_shock_distributes_proportionally_to_omega(omega_table):
    out, report = allocate_shock({"SEC001": 1000.0, "SEC002": 500.0}, omega_table)

    sec1 = out[out["sector_serio"] == "SEC001"].set_index("cvegeo")["shock_ageb"]
    assert sec1["A00"] == pytest.approx(600.0)
    assert sec1["A01"] == pytest.approx(400.0)

    # SEC002: solo A00 tiene ω válido (A10 es 'sin_datos' y queda excluido)
    sec2 = out[out["sector_serio"] == "SEC002"].set_index("cvegeo")["shock_ageb"]
    assert list(sec2.index) == ["A00"]
    assert sec2["A00"] == pytest.approx(500.0)

    assert report.n_sectores_shock == 2
    assert report.n_sectores_distribuidos == 2
    assert report.sectores_sin_cobertura_espacial == []
    assert report.n_agebs_excluidos_por_sector == {"SEC001": 0, "SEC002": 1}
    assert report.total_shock_distribuido == {"SEC001": pytest.approx(1000.0), "SEC002": pytest.approx(500.0)}


def test_allocate_shock_excludes_sectors_without_spatial_coverage(omega_table):
    out, report = allocate_shock({"SEC001": 1000.0, "SEC003": 200.0, "SEC999": 50.0}, omega_table)

    assert set(out["sector_serio"]) == {"SEC001"}
    assert set(report.sectores_sin_cobertura_espacial) == {"SEC003", "SEC999"}
    assert report.n_sectores_shock == 3
    assert report.n_sectores_distribuidos == 1


def test_allocate_shock_returns_geodataframe_with_geometry(omega_table):
    out, _ = allocate_shock({"SEC001": 1000.0}, omega_table)
    assert isinstance(out, gpd.GeoDataFrame)
    assert out.crs == omega_table.crs
    assert out.geometry.notna().all()


def test_allocate_shock_on_empty_shock_returns_empty_geodataframe(omega_table):
    out, report = allocate_shock({}, omega_table)
    assert len(out) == 0
    assert isinstance(out, gpd.GeoDataFrame)
    assert report.n_sectores_shock == 0
    assert report.n_sectores_distribuidos == 0


def test_allocate_shock_flags_omega_not_summing_to_one_without_recomputing_upstream(omega_table):
    # SEC004 solo tiene A00 con ω=0.5 → suma de ω conocida = 0.5, no 1.0.
    out, report = allocate_shock({"SEC004": 100.0}, omega_table)
    assert report.omega_sum_by_sector["SEC004"] == pytest.approx(0.5)
    assert "SEC004" in report.sectores_omega_no_normalizado
    # El reparto SÍ ocurre (no se fuerza normalización): 0.5 * 100 = 50.0
    assert out["shock_ageb"].iloc[0] == pytest.approx(50.0)


def test_allocate_shock_uses_integrity_report_instead_of_recomputing(omega_table):
    # SEC001 suma 1.0 exactamente (no debería marcarse) — pero si el
    # integrity_report ya lo marca como no-normalizado, se respeta esa
    # fuente en vez de recalcular la suma (mismo criterio que diagnostics.py).
    integrity_report = {"sectors_omega_not_summing_to_one": ["SEC001"]}
    out, report = allocate_shock({"SEC001": 1000.0}, omega_table, integrity_report=integrity_report)
    assert report.sectores_omega_no_normalizado == ["SEC001"]
    assert report.omega_sum_by_sector["SEC001"] == pytest.approx(1.0)  # el valor leído no cambia


# ══════════════════════════════════════════════════════════════════════════
# Escenario 2 — WarehouseBuilder real (mismo grid de test_builder.py /
# test_diagnostics.py) → confirma integración end-to-end sin recalcular nada
# ══════════════════════════════════════════════════════════════════════════
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]


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
        ("A7", "999999", LON0 + 0.001, LAT0 + 0.002, "0 a 5 personas"),
        ("A8", "111111", LON0 - 0.30, LAT0 - 0.30, "0 a 5 personas"),
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


def test_allocate_shock_against_real_warehouse_build(real_warehouse_parquet):
    omega_table = load_omega_table(real_warehouse_parquet)
    # SEC001: A00 y A11 (ambos con ω por empleo, según Stage 5)
    out, report = allocate_shock({"SEC001": 1_000_000.0}, omega_table)

    assert set(out["cvegeo"]) == {"A00", "A11"}
    assert out["shock_ageb"].sum() == pytest.approx(1_000_000.0)
    assert report.sectores_sin_cobertura_espacial == []
    assert report.n_agebs_excluidos_por_sector["SEC001"] == 0


def test_generate_shock_ageb_writes_parquet_with_geometry(tmp_path, real_warehouse_parquet):
    output_path = tmp_path / "shock_ageb.parquet"
    gdf, report = generate_shock_ageb(
        {"SEC001": 1_000_000.0, "SEC002": 200_000.0},
        parquet_path=real_warehouse_parquet,
        output_path=output_path,
    )

    assert output_path.exists()
    on_disk = gpd.read_parquet(output_path)
    assert "geometry" in on_disk.columns
    assert on_disk.geometry.notna().all()
    assert len(on_disk) == len(gdf)
    assert isinstance(report, AllocationReport)


def test_generate_shock_ageb_does_not_write_when_write_false(tmp_path, real_warehouse_parquet):
    output_path = tmp_path / "shock_ageb.parquet"
    generate_shock_ageb(
        {"SEC001": 1_000_000.0},
        parquet_path=real_warehouse_parquet,
        output_path=output_path,
        write=False,
    )
    assert not output_path.exists()


def test_generate_shock_ageb_raises_without_warehouse_parquet(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_shock_ageb(
            {"SEC001": 1_000_000.0},
            parquet_path=tmp_path / "no_existe.parquet",
        )


def test_generate_shock_ageb_report_serializes_to_json(tmp_path, real_warehouse_parquet):
    _, report = generate_shock_ageb(
        {"SEC001": 1_000_000.0},
        parquet_path=real_warehouse_parquet,
        write=False,
    )
    output_path = tmp_path / "allocation_report.json"
    report.to_json(output_path)
    on_disk = json.loads(output_path.read_text(encoding="utf-8"))
    assert on_disk["n_sectores_shock"] == report.n_sectores_shock == 1
