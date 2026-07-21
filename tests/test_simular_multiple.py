# tests/test_simular_multiple.py
"""
Pruebas de `ModeloEconomico.simular_multiple()` — Fase 4 del GIS
Workstation (shocks compuestos multi-sector).

Mismo criterio que `tests/test_scenario.py`: `ModeloEconomico` REAL
cargado desde `serio/data/` (nunca mockeado). No hace falta un
warehouse/AGEB sintético aquí porque `simular_multiple()` no toca
nada espacial — es puro álgebra de Leontief a nivel nacional/estatal,
igual que `simular()`.

La propiedad central que se prueba: el operador de Leontief es lineal,
así que `simular_multiple({A: m_a, B: m_b})` debe ser IDÉNTICO
(hasta error de punto flotante) a sumar `simular(A, m_a)` +
`simular(B, m_b)` componente a componente — es la razón matemática por
la que esta función no necesitó ningún cambio en Stage 7/8
(`generate_shock_ageb_from_simulacion` / `propagate`), ya verificado
por separado en este archivo con una integración real.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from serio.loader import ModeloEconomico

SERIO_DATA_PATH = Path(__file__).resolve().parent.parent / "serio" / "data"

# Códigos SCIAN reales (mismos que tests/test_scenario.py)
SECTOR_A = "111"   # Agricultura
SECTOR_B = "112"   # Cría y explotación de animales
ESTADO_KEY = "QUERETARO"


@pytest.fixture(scope="module")
def modelo() -> ModeloEconomico:
    return ModeloEconomico(str(SERIO_DATA_PATH))


@pytest.fixture(scope="module")
def idx_a(modelo) -> int:
    return modelo.scian_idx[SECTOR_A]


@pytest.fixture(scope="module")
def idx_b(modelo) -> int:
    return modelo.scian_idx[SECTOR_B]


# ══════════════════════════════════════════════════════════════════════════
# 1. Superposición — la propiedad que justifica todo el diseño
# ══════════════════════════════════════════════════════════════════════════
def test_multi_sector_equals_sum_of_individual_simulations(modelo, idx_a, idx_b):
    monto_a, monto_b = 1_000_000.0, 500_000.0

    res_a = modelo.simular(ESTADO_KEY, idx_a, monto_a)
    res_b = modelo.simular(ESTADO_KEY, idx_b, monto_b)
    res_multi = modelo.simular_multiple(ESTADO_KEY, {idx_a: monto_a, idx_b: monto_b})

    np.testing.assert_allclose(res_multi["delta_X"], res_a["delta_X"] + res_b["delta_X"], rtol=1e-10)
    np.testing.assert_allclose(res_multi["delta_VA"], res_a["delta_VA"] + res_b["delta_VA"], rtol=1e-10)
    np.testing.assert_allclose(res_multi["delta_E"], res_a["delta_E"] + res_b["delta_E"], rtol=1e-10)
    assert res_multi["delta_X_total_pesos"] == pytest.approx(
        res_a["delta_X_total_pesos"] + res_b["delta_X_total_pesos"]
    )
    assert res_multi["monto_pesos"] == pytest.approx(monto_a + monto_b)


def test_single_sector_matches_simular_exactly(modelo, idx_a):
    """Caso degenerado: un solo sector en `simular_multiple()` debe dar
    exactamente lo mismo que `simular()` -- no es una función distinta,
    es la misma fórmula generalizada."""
    monto = 750_000.0
    res_simple = modelo.simular(ESTADO_KEY, idx_a, monto)
    res_multi = modelo.simular_multiple(ESTADO_KEY, {idx_a: monto})

    np.testing.assert_allclose(res_multi["delta_X"], res_simple["delta_X"], rtol=1e-12)
    assert res_multi["mult_produccion"] == pytest.approx(res_simple["mult_produccion"])
    assert res_multi["delta_X_total_pesos"] == pytest.approx(res_simple["delta_X_total_pesos"])


# ══════════════════════════════════════════════════════════════════════════
# 2. Contrato de salida -- mismo shape que simular(), más shocks_detalle
# ══════════════════════════════════════════════════════════════════════════
def test_output_has_same_keys_as_simular_plus_shocks_detalle(modelo, idx_a, idx_b):
    res_simple = modelo.simular(ESTADO_KEY, idx_a, 1_000_000.0)
    res_multi = modelo.simular_multiple(ESTADO_KEY, {idx_a: 1_000_000.0, idx_b: 500_000.0})

    shared_keys = {
        "delta_X", "delta_VA", "delta_E", "delta_X_total_pesos", "delta_VA_total_pesos",
        "delta_E_total", "monto_mmdp", "monto_pesos", "mult_produccion", "mult_ingreso",
        "mult_empleo", "df_detalle",
    }
    assert shared_keys.issubset(res_simple.keys())
    assert shared_keys.issubset(res_multi.keys())
    assert "shocks_detalle" in res_multi
    assert len(res_multi["shocks_detalle"]) == 2
    assert {d["scian"] for d in res_multi["shocks_detalle"]} == {SECTOR_A, SECTOR_B}


def test_df_detalle_marks_origin_sectors(modelo, idx_a, idx_b):
    res_multi = modelo.simular_multiple(ESTADO_KEY, {idx_a: 1_000_000.0, idx_b: 500_000.0})
    df = res_multi["df_detalle"]
    origen = df[df["es_origen_shock"]]
    assert set(origen["indice"]) == {idx_a, idx_b}
    assert len(origen) == 2


# ══════════════════════════════════════════════════════════════════════════
# 3. Validación de entradas
# ══════════════════════════════════════════════════════════════════════════
def test_empty_shocks_raises(modelo):
    with pytest.raises(ValueError):
        modelo.simular_multiple(ESTADO_KEY, {})


def test_out_of_range_sector_raises(modelo):
    with pytest.raises(ValueError):
        modelo.simular_multiple(ESTADO_KEY, {modelo.n + 10: 1_000_000.0})


def test_negative_shock_supported_as_contraction(modelo, idx_a, idx_b):
    """Un shock compuesto puede mezclar expansión y contracción (p.ej.
    reasignar presupuesto de un sector a otro) -- sigue siendo lineal."""
    res = modelo.simular_multiple(ESTADO_KEY, {idx_a: 1_000_000.0, idx_b: -400_000.0})
    assert res["monto_pesos"] == pytest.approx(600_000.0)


# ══════════════════════════════════════════════════════════════════════════
# 4. Integración real con Stage 7/8 -- confirma que run_simulation_engine
#    consume simular_multiple() sin ningún cambio (Stage 7/8 son
#    agnósticos de cuántos sectores originaron el shock).
# ══════════════════════════════════════════════════════════════════════════
def test_integrates_with_shock_from_resultado_simulacion(modelo, idx_a, idx_b):
    from spatial.allocation.serio_bridge import shock_from_resultado_simulacion

    res_multi = modelo.simular_multiple(ESTADO_KEY, {idx_a: 1_000_000.0, idx_b: 500_000.0})
    shock_series = shock_from_resultado_simulacion(res_multi)
    assert shock_series[SECTOR_A] == pytest.approx(res_multi["df_detalle"].set_index("scian").loc[SECTOR_A, "delta_X_pesos"])
    assert len(shock_series) == modelo.n
