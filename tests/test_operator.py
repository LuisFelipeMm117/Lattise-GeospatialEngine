# tests/test_operator.py
"""
Pruebas de spatial.simulation.operator — operador de propagación espacial
Y = (I − ρW)^-1 · S (Incremento 2, "Stage 8B").

Sigue el mismo criterio que tests/test_matrix.py y tests/test_allocation.py:
  1. Fixtures AGEB sintéticas EXACTAMENTE iguales (grid 2x2, grid con isla)
     para construir una `SpatialMatrix` real vía `SpatialGraphBuilder` +
     `to_graph_files()` (Spatial Graph Builder, cerrado) — nunca mockeada.
  2. Un `shock_ageb.parquet` genuino, producido por
     `allocation.allocator.allocate_shock()` (Stage 7, cerrado) sobre una
     `OmegaTable` sintética construida directamente (sin recalcular ω ni
     el Spatial Join) — mismo criterio que el "Escenario 1" de
     tests/test_allocation.py.
  3. Casos de borde de formato (columnas faltantes, AGEBs desconocidos)
     se ejercen contra parquets escritos a mano, para no depender de que
     el pipeline real produzca esas inconsistencias por sí solo.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.allocation.allocator import allocate_shock
from spatial.allocation.weights import OmegaTable
from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.matrix import SpatialMatrix
from spatial.simulation.operator import (
    DEFAULT_COND_TOL,
    RHO_ABS_BOUND,
    InvalidRhoError,
    PropagationReport,
    ShockAlignmentError,
    ShockVectorReport,
    SingularPropagationMatrixError,
    load_shock_vector,
    neumann_series_sum,
    propagate,
    spectral_radius,
    validate_rho,
)
from spatial.warehouse.ageb_loader import AGEBLoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — idénticas a tests/test_matrix.py
# ══════════════════════════════════════════════════════════════════════════
def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _grid_2x2_gdf() -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    raw = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    return AGEBLoader().normalize(raw)


def _grid_with_island_gdf() -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    polys.append(_square(500, 500))
    ids.append("ISLA")
    raw = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    return AGEBLoader().normalize(raw)


def _write_gal_and_metadata(tmp_path, criterio="queen", gdf=None):
    gdf = gdf if gdf is not None else _grid_2x2_gdf()
    gb = SpatialGraphBuilder(criterio=criterio)
    graph = gb.build(gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph,
        gal_path=tmp_path / "graph.gal",
        metadata_path=tmp_path / "graph_metadata.json",
    )
    return graph, gal_path, metadata_path


def _spatial_matrix(tmp_path, criterio="queen", gdf=None) -> SpatialMatrix:
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio=criterio, gdf=gdf)
    return SpatialMatrix.from_gal(gal_path, metadata_path)


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — shock_ageb.parquet genuino (mismo criterio que test_allocation.py)
# ══════════════════════════════════════════════════════════════════════════
def _omega_table_from_allocations(gdf: gpd.GeoDataFrame, allocations: dict) -> OmegaTable:
    rows = []
    for sector, omega_por_ageb in allocations.items():
        for cvegeo, omega in omega_por_ageb.items():
            rows.append((cvegeo, sector, omega, "empleo"))
    table = pd.DataFrame(rows, columns=["cvegeo", "sector_serio", "omega", "omega_metodo"])
    geometry = gdf.set_index("cvegeo")["geometry"]
    return OmegaTable(table=table, geometry=geometry, crs=gdf.crs, id_col="cvegeo", sector_col="sector_serio")


def _write_shock_ageb_parquet(tmp_path, gdf, allocations, shock, filename="shock_ageb.parquet"):
    omega_table = _omega_table_from_allocations(gdf, allocations)
    out_gdf, _report = allocate_shock(shock, omega_table)
    path = tmp_path / filename
    out_gdf.to_parquet(path)
    return path


# ══════════════════════════════════════════════════════════════════════════
# load_shock_vector — agregación S_g = Σ_s shock_ageb_{g,s}, alineada a sm.ids
# ══════════════════════════════════════════════════════════════════════════
def test_load_shock_vector_aggregates_across_sectors_and_aligns_to_matrix_ids(tmp_path):
    gdf = _grid_2x2_gdf()
    sm = _spatial_matrix(tmp_path, criterio="queen", gdf=gdf)

    allocations = {
        "SEC001": {"A00": 0.6, "A01": 0.4},
        "SEC002": {"A10": 1.0},
    }
    shock = {"SEC001": 1000.0, "SEC002": 500.0}
    parquet_path = _write_shock_ageb_parquet(tmp_path, gdf, allocations, shock)

    S, report = load_shock_vector(sm, parquet_path=parquet_path)

    assert S[sm.index_of("A00")] == pytest.approx(600.0)
    assert S[sm.index_of("A01")] == pytest.approx(400.0)
    assert S[sm.index_of("A10")] == pytest.approx(500.0)
    assert S[sm.index_of("A11")] == pytest.approx(0.0)

    assert report.n_nodos_matrix == 4
    assert report.n_agebs_desconocidos == 0
    assert report.agebs_desconocidos == []
    assert report.n_agebs_sin_shock == 1
    assert report.suma_shock_total == pytest.approx(1500.0)


def test_load_shock_vector_raises_filenotfound(tmp_path):
    gdf = _grid_2x2_gdf()
    sm = _spatial_matrix(tmp_path, gdf=gdf)
    with pytest.raises(FileNotFoundError):
        load_shock_vector(sm, parquet_path=tmp_path / "no_existe.parquet")


def test_load_shock_vector_raises_on_missing_columns(tmp_path):
    gdf = _grid_2x2_gdf()
    sm = _spatial_matrix(tmp_path, gdf=gdf)

    bad = pd.DataFrame({"cvegeo": ["A00"], "otra_columna": [1.0]})
    path = tmp_path / "malo.parquet"
    bad.to_parquet(path)

    with pytest.raises(ValueError):
        load_shock_vector(sm, parquet_path=path)


def test_load_shock_vector_raises_shockalignmenterror_on_unknown_ageb_when_strict(tmp_path):
    gdf = _grid_2x2_gdf()
    sm = _spatial_matrix(tmp_path, gdf=gdf)

    df = pd.DataFrame({
        "cvegeo": ["A00", "FANTASMA"],
        "sector_serio": ["SEC001", "SEC001"],
        "shock_ageb": [600.0, 999.0],
    })
    path = tmp_path / "con_fantasma.parquet"
    df.to_parquet(path)

    with pytest.raises(ShockAlignmentError):
        load_shock_vector(sm, parquet_path=path, strict=True)


def test_load_shock_vector_strict_false_excludes_unknown_and_reports(tmp_path):
    gdf = _grid_2x2_gdf()
    sm = _spatial_matrix(tmp_path, gdf=gdf)

    df = pd.DataFrame({
        "cvegeo": ["A00", "FANTASMA"],
        "sector_serio": ["SEC001", "SEC001"],
        "shock_ageb": [600.0, 999.0],
    })
    path = tmp_path / "con_fantasma.parquet"
    df.to_parquet(path)

    S, report = load_shock_vector(sm, parquet_path=path, strict=False)

    assert S[sm.index_of("A00")] == pytest.approx(600.0)
    assert S.sum() == pytest.approx(600.0)
    assert report.n_agebs_desconocidos == 1
    assert report.agebs_desconocidos == ["FANTASMA"]


def test_shock_vector_report_to_dict_and_json_roundtrip(tmp_path):
    gdf = _grid_2x2_gdf()
    sm = _spatial_matrix(tmp_path, gdf=gdf)
    allocations = {"SEC001": {"A00": 1.0}}
    shock = {"SEC001": 100.0}
    parquet_path = _write_shock_ageb_parquet(tmp_path, gdf, allocations, shock)

    _, report = load_shock_vector(sm, parquet_path=parquet_path)
    report_dict = report.to_dict()
    assert report_dict["suma_shock_total"] == pytest.approx(100.0)

    out_path = tmp_path / "shock_vector_report.json"
    report.to_json(out_path)
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == report_dict


# ══════════════════════════════════════════════════════════════════════════
# spectral_radius — nunca asumido, siempre calculado
# ══════════════════════════════════════════════════════════════════════════
def test_spectral_radius_of_connected_queen_grid_is_approximately_one(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    assert spectral_radius(sm.W) == pytest.approx(1.0, abs=1e-8)


def test_spectral_radius_with_island_still_approximately_one(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen", gdf=_grid_with_island_gdf())
    assert spectral_radius(sm.W) == pytest.approx(1.0, abs=1e-8)


def test_spectral_radius_of_all_island_matrix_is_zero():
    W = np.zeros((3, 3))
    assert spectral_radius(W) == 0.0


# ══════════════════════════════════════════════════════════════════════════
# validate_rho — rango absoluto (-1, 1) y rango efectivo (1/radio_espectral)
# ══════════════════════════════════════════════════════════════════════════
def test_validate_rho_accepts_valid_range():
    validate_rho(0.5, radio_espectral=1.0)
    validate_rho(-0.9, radio_espectral=1.0)
    validate_rho(0.0, radio_espectral=1.0)


@pytest.mark.parametrize("rho", [1.0, -1.0, 1.5, -2.3])
def test_validate_rho_rejects_absolute_bound(rho):
    with pytest.raises(InvalidRhoError):
        validate_rho(rho, radio_espectral=0.1)


def test_validate_rho_rejects_beyond_effective_bound_for_high_spectral_radius():
    # radio_espectral=2.0 → límite efectivo = 0.5, más estricto que (-1, 1)
    with pytest.raises(InvalidRhoError):
        validate_rho(0.6, radio_espectral=2.0)
    validate_rho(0.4, radio_espectral=2.0)  # dentro del límite efectivo, no debe lanzar


def test_validate_rho_skips_effective_bound_when_spectral_radius_is_zero():
    validate_rho(0.999, radio_espectral=0.0)


def test_validate_rho_rejects_non_finite_and_non_numeric():
    with pytest.raises(InvalidRhoError):
        validate_rho(float("nan"), radio_espectral=1.0)
    with pytest.raises(InvalidRhoError):
        validate_rho(float("inf"), radio_espectral=1.0)
    with pytest.raises(InvalidRhoError):
        validate_rho("no_es_un_numero", radio_espectral=1.0)


# ══════════════════════════════════════════════════════════════════════════
# propagate — identidad en ρ=0, comparación con inversión directa, validaciones
# ══════════════════════════════════════════════════════════════════════════
def test_propagate_identity_when_rho_is_zero(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 200.0, 300.0, 400.0])

    Y, report = propagate(sm, S, rho=0.0)

    assert np.allclose(Y, S)
    assert report.rho == 0.0
    assert report.suma_S == pytest.approx(S.sum())
    assert report.suma_Y == pytest.approx(S.sum())
    assert report.multiplicador_global == pytest.approx(1.0)
    assert report.condicion_I_menos_rhoW == pytest.approx(1.0, abs=1e-6)


def test_propagate_matches_direct_matrix_inversion(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 50.0, -20.0])
    rho = 0.3

    Y, _ = propagate(sm, S, rho=rho)

    n = len(sm.ids)
    Y_esperado = np.linalg.inv(np.eye(n) - rho * sm.W) @ S
    assert np.allclose(Y, Y_esperado)


def test_propagate_reflects_higher_diffusion_at_higher_rho(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.zeros(len(sm.ids))
    S[sm.index_of("A00")] = 1000.0

    Y_bajo, _ = propagate(sm, S, rho=0.1)
    Y_alto, _ = propagate(sm, S, rho=0.5)

    idx_vecino = sm.index_of("A01")
    assert Y_alto[idx_vecino] > Y_bajo[idx_vecino] > 0.0


def test_propagate_isolated_node_output_equals_its_own_shock_directly(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen", gdf=_grid_with_island_gdf())
    S = np.zeros(len(sm.ids))
    S[sm.index_of("ISLA")] = 250.0
    S[sm.index_of("A00")] = 100.0

    Y, _ = propagate(sm, S, rho=0.5)

    assert Y[sm.index_of("ISLA")] == pytest.approx(250.0)


def test_propagate_all_island_matrix_allows_any_rho_within_absolute_bound():
    ids = ["A", "B", "C"]
    neighbors = {"A": [], "B": [], "C": []}
    W = np.zeros((3, 3))
    from spatial.simulation.matrix import SpatialMatrixReport

    sm = SpatialMatrix(
        id_col="cvegeo", ids=ids, neighbors=neighbors, W=W, criterio=None,
        report=SpatialMatrixReport(n_nodos=3, n_islas=3, islas=ids),
    )
    S = np.array([10.0, 20.0, 30.0])

    Y, report = propagate(sm, S, rho=0.99)
    assert np.allclose(Y, S)
    assert report.rho_max_efectivo == float("inf")


def test_propagate_accepts_pandas_series_aligned_by_id_not_position(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    # Orden deliberadamente distinto al de sm.ids
    S_series = pd.Series(
        {"A11": 400.0, "A00": 100.0, "A10": 300.0, "A01": 200.0}
    )

    Y_series, _ = propagate(sm, S_series, rho=0.2)

    S_alineado = np.array([S_series[cvegeo] for cvegeo in sm.ids])
    Y_array, _ = propagate(sm, S_alineado, rho=0.2)

    assert np.allclose(Y_series, Y_array)


def test_propagate_series_missing_id_raises_shockalignmenterror(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S_incompleto = pd.Series({"A00": 100.0, "A01": 200.0, "A10": 300.0})  # falta A11

    with pytest.raises(ShockAlignmentError):
        propagate(sm, S_incompleto, rho=0.2)


def test_propagate_raises_on_shape_mismatch(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    with pytest.raises(ValueError):
        propagate(sm, np.array([1.0, 2.0]), rho=0.2)


def test_propagate_raises_on_non_finite_values_in_S(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([1.0, np.nan, 3.0, 4.0])
    with pytest.raises(ValueError):
        propagate(sm, S, rho=0.2)


@pytest.mark.parametrize("rho", [1.0, -1.0, 1.2, -5.0])
def test_propagate_raises_invalidrho_at_or_beyond_absolute_bound(tmp_path, rho):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 0.0, 0.0])
    with pytest.raises(InvalidRhoError):
        propagate(sm, S, rho=rho)


def test_propagate_raises_singular_via_artificially_strict_cond_tol(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 0.0, 0.0])
    with pytest.raises(SingularPropagationMatrixError):
        propagate(sm, S, rho=0.5, cond_tol=1.0)


def test_propagate_raises_singular_near_effective_rho_boundary(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 0.0, 0.0])
    radio = spectral_radius(sm.W)
    rho_casi_limite = (1.0 / radio) * (1.0 - 1e-13)
    with pytest.raises(SingularPropagationMatrixError):
        propagate(sm, S, rho=rho_casi_limite, cond_tol=DEFAULT_COND_TOL)


def test_propagate_report_fields_and_serialization(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="rook")
    S = np.array([100.0, 200.0, 300.0, 400.0])
    Y, report = propagate(sm, S, rho=0.25)

    assert isinstance(report, PropagationReport)
    assert report.n_nodos == 4
    assert report.criterio == "rook"
    assert report.n_agebs_con_shock == 4

    report_dict = report.to_dict()
    assert report_dict["rho"] == pytest.approx(0.25)

    out_path = tmp_path / "propagation_report.json"
    report.to_json(out_path)
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == report_dict

    assert "propagation report" in report.summary().lower()


def test_rho_abs_bound_constant_is_one():
    assert RHO_ABS_BOUND == 1.0


# ══════════════════════════════════════════════════════════════════════════
# neumann_series_sum — prueba de convergencia independiente de propagate()
# ══════════════════════════════════════════════════════════════════════════
def test_neumann_series_identity_at_rho_zero(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([10.0, 20.0, 30.0, 40.0])

    Y_approx, n_usados, convergio = neumann_series_sum(sm.W, rho=0.0, S=S, max_terms=50)

    assert np.allclose(Y_approx, S)
    assert convergio is True
    assert n_usados == 1


def test_neumann_series_converges_to_direct_solution_for_valid_rho(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 50.0, -20.0])
    rho = 0.3

    Y_exacto, _ = propagate(sm, S, rho=rho)
    Y_approx, n_usados, convergio = neumann_series_sum(
        sm.W, rho=rho, S=S, max_terms=500, tol=1e-12
    )

    assert convergio is True
    assert n_usados < 500
    assert np.allclose(Y_approx, Y_exacto, atol=1e-8)


def test_neumann_series_error_decreases_monotonically_with_more_terms(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 50.0, -20.0])
    rho = 0.5

    Y_exacto, _ = propagate(sm, S, rho=rho)

    Y_1, _, _ = neumann_series_sum(sm.W, rho=rho, S=S, max_terms=1, tol=0.0)
    Y_5, _, _ = neumann_series_sum(sm.W, rho=rho, S=S, max_terms=5, tol=0.0)
    Y_20, _, _ = neumann_series_sum(sm.W, rho=rho, S=S, max_terms=20, tol=0.0)

    err_1 = np.linalg.norm(Y_1 - Y_exacto)
    err_5 = np.linalg.norm(Y_5 - Y_exacto)
    err_20 = np.linalg.norm(Y_20 - Y_exacto)

    assert err_1 > err_5 > err_20


def test_neumann_series_does_not_converge_flag_false_when_terms_insufficient(tmp_path):
    sm = _spatial_matrix(tmp_path, criterio="queen")
    S = np.array([100.0, 0.0, 50.0, -20.0])
    rho = 0.5

    _, n_usados, convergio = neumann_series_sum(sm.W, rho=rho, S=S, max_terms=1, tol=1e-15)

    assert convergio is False
    assert n_usados == 1