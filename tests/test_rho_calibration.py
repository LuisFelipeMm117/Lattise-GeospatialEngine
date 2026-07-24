# tests/test_rho_calibration.py
"""
Pruebas de `spatial.simulation.calibration` — calibración de ρ por
autocorrelación espacial (Moran's I). Ver el docstring del módulo:
esto NO es una estimación causal (bloqueada por falta de panel
temporal), es una calibración por momentos.

Mismo criterio que `tests/test_run_rho_sensitivity.py`: warehouse.parquet
y graph.gal GENUINOS (nunca mockeados) para las pruebas de integración;
`morans_i()` se prueba aparte con vectores sintéticos de patrón conocido
(no hace falta ningún artefacto en disco para eso).
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.calibration import (
    METODOLOGIA,
    calibrate_rho,
    morans_i,
    observed_peso_ageb,
)
from spatial.simulation.matrix import SpatialMatrix
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]


# ══════════════════════════════════════════════════════════════════════════
# 1. morans_i() -- primitiva pura, con patrones sintéticos de I conocido
# ══════════════════════════════════════════════════════════════════════════
def test_morans_i_clustered_pattern_is_positive():
    """4 nodos en línea (0-1-2-3), valores [0,0,10,10] -- alta similitud
    entre vecinos -> I positivo."""
    W = np.array([
        [0, 1, 0, 0],
        [1, 0, 1, 0],
        [0, 1, 0, 1],
        [0, 0, 1, 0],
    ], dtype=float)
    x = np.array([0.0, 0.0, 10.0, 10.0])
    assert morans_i(x, W) > 0


def test_morans_i_checkerboard_pattern_is_negative():
    """4 nodos en línea, valores alternados [0,10,0,10] -- vecinos
    siempre distintos -> I negativo."""
    W = np.array([
        [0, 1, 0, 0],
        [1, 0, 1, 0],
        [0, 1, 0, 1],
        [0, 0, 1, 0],
    ], dtype=float)
    x = np.array([0.0, 10.0, 0.0, 10.0])
    assert morans_i(x, W) < 0


def test_morans_i_constant_vector_is_zero_not_nan():
    """Varianza nula -> 0.0 explícito, nunca división por cero silenciosa."""
    W = np.array([[0, 1], [1, 0]], dtype=float)
    x = np.array([5.0, 5.0])
    assert morans_i(x, W) == 0.0


def test_morans_i_empty_vector_is_zero():
    assert morans_i(np.array([]), np.zeros((0, 0))) == 0.0


def test_morans_i_zero_weight_matrix_is_zero():
    W = np.zeros((3, 3))
    x = np.array([1.0, 2.0, 3.0])
    assert morans_i(x, W) == 0.0


# ══════════════════════════════════════════════════════════════════════════
# Fixtures de integración -- mismo patrón que test_run_rho_sensitivity.py
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
        warehouse, parquet_path=tmp_path / "warehouse.parquet", metadata_path=tmp_path / "metadata.json",
    )
    return parquet_path


@pytest.fixture
def graph_files(tmp_path, ageb_gdf):
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(ageb_gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph, gal_path=tmp_path / "graph.gal", metadata_path=tmp_path / "graph_metadata.json",
    )
    return gal_path, metadata_path


def _fake_resultado_simulacion(sectores, delta_x_pesos) -> dict:
    df_detalle = pd.DataFrame({"scian": sectores, "delta_X_pesos": delta_x_pesos})
    return {"delta_X": np.asarray(delta_x_pesos) * 1e-6, "df_detalle": df_detalle}


# ══════════════════════════════════════════════════════════════════════════
# 2. observed_peso_ageb() -- Σω por AGEB, alineado a sm.ids
# ══════════════════════════════════════════════════════════════════════════
def test_observed_peso_ageb_aligned_to_sm_ids(warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    x_obs = observed_peso_ageb(warehouse_parquet_path, sm)

    assert len(x_obs) == len(sm.ids)
    assert (x_obs >= 0).all()
    # Total de omega en el warehouse == suma del vector alineado (ningún
    # AGEB se pierde ni se duplica en el reindex).
    df = pd.read_parquet(warehouse_parquet_path, columns=["omega"])
    assert x_obs.sum() == pytest.approx(df["omega"].sum(), rel=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# 3. calibrate_rho() -- integración completa
# ══════════════════════════════════════════════════════════════════════════
def test_calibrate_rho_returns_valid_result(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    result = calibrate_rho(
        resultado,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_calib.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
        n_grid_coarse=15, n_grid_fine=11,
    )

    assert result.convergio
    assert -0.95 <= result.rho_calibrado <= 0.95
    assert result.n_agebs == 4
    assert result.criterio_espacial == "queen"
    assert not result.grid.empty
    assert METODOLOGIA in result.criterio_metodologico
    assert result.diferencia_absoluta == pytest.approx(
        abs(result.morans_i_modelo - result.morans_i_observado)
    )


def test_calibrate_rho_grid_search_finds_a_reasonable_minimum(tmp_path, warehouse_parquet_path, graph_files):
    """El ρ calibrado debe estar entre los mejores candidatos evaluados
    -- no cualquier valor, el que minimiza la diferencia contra el
    Moran's I observado."""
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    result = calibrate_rho(
        resultado,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_calib2.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
        n_grid_coarse=21, n_grid_fine=21,
    )
    assert result.diferencia_absoluta == pytest.approx(result.grid["diferencia_absoluta"].min(), abs=1e-9)


def test_calibrate_rho_summary_includes_methodology_disclaimer(tmp_path, warehouse_parquet_path, graph_files):
    """Cualquier consumidor que llame a `.summary()` debe recibir el
    descargo metodológico -- no puede omitirse por accidente."""
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    result = calibrate_rho(
        resultado,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_calib3.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
        n_grid_coarse=11, n_grid_fine=11,
    )
    assert "NO es una estimación causal" in result.summary()


def test_calibrate_rho_stage7_runs_once(tmp_path, warehouse_parquet_path, graph_files, monkeypatch):
    """Mismo criterio que run_rho_sensitivity: Stage 7 se calcula UNA
    sola vez, sin importar cuántos ρ evalúe la grilla (41+41=82 aquí)."""
    import spatial.simulation.calibration as calib_mod

    original = calib_mod.generate_shock_ageb_from_simulacion
    calls = []

    def _counting_wrapper(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(calib_mod, "generate_shock_ageb_from_simulacion", _counting_wrapper)

    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    calib_mod.calibrate_rho(
        resultado,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_calib4.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )
    assert len(calls) == 1, f"Stage 7 se llamó {len(calls)} veces; debía ser 1."


def test_calibrate_rho_degenerate_zero_coverage_does_not_raise(tmp_path, warehouse_parquet_path, graph_files):
    """Sector sin cobertura en el warehouse (ΣS=0) -- no debe reventar,
    debe devolver un resultado con convergio=False (grid vacía) o un
    resultado válido con diferencia_absoluta consistente, nunca una
    excepción no capturada."""
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC_NO_EXISTE"], [1_000_000.0])

    result = calibrate_rho(
        resultado,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_calib5.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
        n_grid_coarse=9, n_grid_fine=9,
    )
    assert isinstance(result.rho_calibrado, float)
