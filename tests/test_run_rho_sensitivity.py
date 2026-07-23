# tests/test_run_rho_sensitivity.py
"""
Pruebas de `spatial.simulation.engine.run_rho_sensitivity` — Fase 5 del
GIS Workstation (análisis de sensibilidad sobre ρ).

Mismo criterio que `tests/test_engine.py`: warehouse.parquet y
graph.gal GENUINOS (Stage 5 / Spatial Graph Builder, cerrados), un
`resultado_simulacion` falso que imita el contrato de
`ModeloEconomico.simular()`. No se reprueba la matemática de
`propagate()` en sí (ya cubierta por `test_operator.py`) -- el
objetivo es validar que el BARRIDO reutiliza S/W una sola vez y llama
a `propagate()` correctamente por cada ρ, incluyendo el manejo de
valores de ρ inválidos.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.engine import run_rho_sensitivity, run_simulation_engine
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
# 1. El barrido reproduce exactamente lo que da run_simulation_engine()
#    para cada ρ, uno por uno -- no es una aproximación distinta.
# ══════════════════════════════════════════════════════════════════════════
def test_sweep_matches_run_simulation_engine_per_rho(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0]
    )
    rho_values = [0.0, 0.2, 0.4]

    df_sens, meta = run_rho_sensitivity(
        resultado, rho_values,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_sweep.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )

    assert len(df_sens) == 3
    assert meta["n_rho_invalidos"] == 0

    for rho in rho_values:
        _gdf, report = run_simulation_engine(
            resultado, rho=rho,
            warehouse_parquet_path=warehouse_parquet_path,
            shock_ageb_output_path=tmp_path / f"shock_ageb_check_{rho}.parquet",
            gal_path=gal_path, metadata_path=metadata_path,
        )
        row = df_sens[np.isclose(df_sens["rho"], rho)].iloc[0]
        assert row["suma_Y"] == pytest.approx(report.shock_total_propagado)
        assert row["multiplicador_global"] == pytest.approx(report.multiplicador_global)


# ══════════════════════════════════════════════════════════════════════════
# 2. ρ=0 -> Y=S exactamente (identidad, ya probado en test_operator.py --
#    aquí solo se confirma que el barrido preserva esa propiedad).
# ══════════════════════════════════════════════════════════════════════════
def test_rho_zero_gives_multiplier_one(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    df_sens, _meta = run_rho_sensitivity(
        resultado, [0.0],
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )
    assert df_sens.iloc[0]["suma_S"] == pytest.approx(df_sens.iloc[0]["suma_Y"])
    assert df_sens.iloc[0]["multiplicador_global"] == pytest.approx(1.0)


# ══════════════════════════════════════════════════════════════════════════
# 3. Monotonía esperada: mayor |ρ| -> mayor multiplicador (para W no nula)
# ══════════════════════════════════════════════════════════════════════════
def test_multiplier_increases_with_rho(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    df_sens, _meta = run_rho_sensitivity(
        resultado, [0.0, 0.2, 0.4, 0.6],
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )
    mults = df_sens.sort_values("rho")["multiplicador_global"].tolist()
    assert mults == sorted(mults)
    assert mults[-1] > mults[0]


# ══════════════════════════════════════════════════════════════════════════
# 4. ρ inválido (fuera de rango) no aborta el barrido -- se omite y se
#    reporta en meta["errores"].
# ══════════════════════════════════════════════════════════════════════════
def test_invalid_rho_is_skipped_not_raised(tmp_path, warehouse_parquet_path, graph_files):
    """ρ fuera del rango teórico absoluto (-1, 1) -- válido sin importar
    el radio espectral de esta W en particular (para W fila-estandarizada,
    radio_espectral <= 1, así que el límite absoluto es siempre el que
    manda para |ρ| >= 1)."""
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    df_sens, meta = run_rho_sensitivity(
        resultado, [0.2, 1.5, -1.5],
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )
    assert len(df_sens) == 1
    assert df_sens.iloc[0]["rho"] == pytest.approx(0.2)
    assert meta["n_rho_invalidos"] == 2
    assert {e["rho"] for e in meta["errores"]} == {1.5, -1.5}


def test_meta_reports_radio_espectral_and_rho_max(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    _df_sens, meta = run_rho_sensitivity(
        resultado, [0.1, 0.2],
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )
    assert meta["radio_espectral_W"] >= 0.0
    assert meta["rho_max_efectivo"] > 0.0
    assert meta["criterio"] == "queen"
    assert meta["n_agebs"] == 4


# ══════════════════════════════════════════════════════════════════════════
# 5. Reutiliza S/W una sola vez -- no recalcula Stage 7 por cada ρ.
#    Se verifica indirectamente: el shock_ageb.parquet en disco solo se
#    escribe UNA vez (mismo timestamp de modificación tras el barrido
#    completo), no una vez por cada ρ evaluado.
# ══════════════════════════════════════════════════════════════════════════
def test_stage7_runs_once_not_per_rho(tmp_path, warehouse_parquet_path, graph_files, monkeypatch):
    """Prueba real (no solo de resultado, de COMPORTAMIENTO): cuenta las
    llamadas a `generate_shock_ageb_from_simulacion` (Stage 7) durante un
    barrido de 5 valores de ρ -- debe ser exactamente 1, sin importar
    cuántos ρ se evalúen."""
    import spatial.simulation.engine as engine_mod

    original = engine_mod.generate_shock_ageb_from_simulacion
    calls = []

    def _counting_wrapper(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "generate_shock_ageb_from_simulacion", _counting_wrapper)

    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0])

    engine_mod.run_rho_sensitivity(
        resultado, [0.1, 0.2, 0.3, 0.4, 0.5],
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb_once.parquet",
        gal_path=gal_path, metadata_path=metadata_path,
    )
    assert len(calls) == 1, f"Stage 7 se llamó {len(calls)} veces para 5 valores de ρ; debía ser 1."
