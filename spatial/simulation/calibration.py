# spatial/simulation/calibration.py
"""
Calibración de ρ por autocorrelación espacial (Moran's I).

LO QUE ESTO NO ES — LÉASE ANTES DE USAR: este módulo NO estima
causalmente el parámetro de difusión espacial ρ. Una estimación causal
requiere datos de panel temporal (¿cómo se propagó un shock real a lo
largo del tiempo?) — eso sigue bloqueado explícitamente en
`spatial/allocation/simulation.py` y `spatial/simulation/operator.py`
("SEE-Estimación... pendiente de datos de panel DENUE"). Ese bloqueo
NO se resuelve con este módulo. Sigue siendo un vacío de datos, no de
código.

LO QUE ESTO SÍ ES: una calibración por momentos (moment matching),
técnica establecida en econometría espacial aplicada cuando no hay
panel temporal disponible. Se elige ρ de forma que el patrón de
agrupamiento espacial de un shock PROPAGADO (Y) sea consistente con el
patrón de agrupamiento espacial YA OBSERVADO en la actividad económica
real de la región (peso ω por AGEB, Stage 5, `warehouse.parquet`,
columna `omega` — la misma que usa
`spatial.decision_support.aggregation.build_ageb_universe` para
`peso_total_ageb`; se recalcula aquí con un `groupby().sum()` propio
en vez de importar ese módulo para no invertir la dirección de
dependencia entre `spatial/simulation/` y `spatial/decision_support/`,
que son módulos hermanos).

El supuesto detrás de esta calibración —"un shock nuevo se dispersa
espacialmente con una intensidad de agrupamiento similar a la que ya
exhibe la geografía económica existente"— es razonable pero NO está
demostrado empíricamente para este contexto. Cualquier UI/API/reporte
que consuma `calibrate_rho()` DEBE etiquetar el resultado como "ρ
calibrado", nunca "ρ óptimo" ni "ρ estimado" a secas — ver
`RhoCalibrationResult.criterio_metodologico`, que lleva ese texto
embebido para que ningún consumidor lo omita por accidente.

Encadena exactamente los mismos building blocks cerrados que
`spatial.simulation.engine.run_simulation_engine` /
`run_rho_sensitivity` — Stage 7 y Stage 8A se ejecutan UNA sola vez
(no dependen de ρ), y `propagate()` (Stage 8B, CERRADO) se llama una
vez por cada ρ evaluado en la grilla de búsqueda. No se reimplementa
`(I − ρW)^-1` en ningún lugar de este archivo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from spatial.allocation.serio_bridge import (
    DEFAULT_DELTA_COL,
    DEFAULT_SECTOR_COL,
    SHOCK_AGEB_PARQUET,
    generate_shock_ageb_from_simulacion,
)
from spatial.config import AGEB_ID_COL, GRAPH_GAL_PATH, GRAPH_METADATA_JSON, WAREHOUSE_PARQUET
from spatial.simulation.matrix import SpatialMatrix
from spatial.simulation.operator import (
    DEFAULT_COND_TOL,
    DEFAULT_SHOCK_COL,
    InvalidRhoError,
    SingularPropagationMatrixError,
    load_shock_vector,
    propagate,
)
from spatial.warehouse.builder import SECTOR_COL

METODOLOGIA = (
    "Calibrado por autocorrelación espacial (Moran's I) contra el patrón de "
    "agrupamiento YA OBSERVADO en la actividad económica real (peso ω por AGEB, "
    "Stage 5) — NO es una estimación causal del parámetro de difusión espacial. "
    "Una estimación causal requiere datos de panel temporal, actualmente no "
    "disponibles (ver spatial/allocation/simulation.py)."
)


# ══════════════════════════════════════════════════════════════════════════
# Primitivas puras — testeables sin tocar disco
# ══════════════════════════════════════════════════════════════════════════
def morans_i(x: np.ndarray, W: np.ndarray) -> float:
    """Índice de Moran clásico:

        I = (n / S0) · [ Σᵢⱼ wᵢⱼ (xᵢ − x̄)(xⱼ − x̄) ] / [ Σᵢ (xᵢ − x̄)² ]

    `x` : vector de longitud n, en el MISMO orden que las filas/columnas
          de `W` (típicamente `sm.ids`).
    `W` : matriz de pesos espaciales (funciona con cualquier W válida,
          fila-estandarizada o no — `S0 = W.sum()` se calcula, no se
          asume).

    Devuelve 0.0 (explícito, no NaN) si la varianza de `x` es
    numéricamente nula o si `W` no tiene ningún peso positivo — nunca
    divide por cero en silencio.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return 0.0
    xbar = x.mean()
    dx = x - xbar
    den = float((dx ** 2).sum())
    S0 = float(W.sum())
    if den <= 1e-12 or S0 <= 1e-12:
        return 0.0
    num = float(dx @ W @ dx)
    return (n / S0) * (num / den)


def observed_peso_ageb(warehouse_parquet_path: str | Path, sm: SpatialMatrix) -> np.ndarray:
    """Peso económico observado por AGEB — Σω (Stage 5, `omega`,
    `warehouse.parquet`) agrupado por AGEB, alineado al mismo orden que
    `sm.ids` (para ser directamente comparable con `Y` en `propagate()`).
    AGEBs sin registro en el warehouse (o sin `omega` calculado) quedan
    en 0.0, explícito, nunca NaN silencioso."""
    df = pd.read_parquet(warehouse_parquet_path, columns=[AGEB_ID_COL, "omega"])
    peso_by_ageb = df.groupby(AGEB_ID_COL)["omega"].sum(min_count=1)
    return peso_by_ageb.reindex(sm.ids).fillna(0.0).to_numpy()


# ══════════════════════════════════════════════════════════════════════════
# Resultado de la calibración
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class RhoCalibrationResult:
    rho_calibrado: float
    morans_i_observado: float
    morans_i_modelo: float
    diferencia_absoluta: float
    convergio: bool
    criterio_espacial: Optional[str]
    n_agebs: int
    n_rho_evaluados: int
    grid: pd.DataFrame = field(repr=False)
    criterio_metodologico: str = METODOLOGIA

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "grid"}
        d["grid"] = self.grid.to_dict(orient="records")
        return d

    def summary(self) -> str:
        estado = "convergió" if self.convergio else "NO convergió (ver grid)"
        return (
            f"ρ calibrado = {self.rho_calibrado:.4f} ({estado})\n"
            f"Moran's I observado (actividad real) = {self.morans_i_observado:.4f}\n"
            f"Moran's I del modelo (shock propagado con este ρ) = {self.morans_i_modelo:.4f}\n"
            f"Diferencia absoluta = {self.diferencia_absoluta:.4f}\n"
            f"{self.criterio_metodologico}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Orquestador — búsqueda en grilla (coarse → fine), sin recalcular
# Stage 7 / Stage 8A más de una vez.
# ══════════════════════════════════════════════════════════════════════════
def calibrate_rho(
    resultado_simulacion: Mapping[str, Any],
    rho_bounds: tuple[float, float] = (-0.95, 0.95),
    n_grid_coarse: int = 15,
    n_grid_fine: int = 11,
    warehouse_parquet_path: str | Path = WAREHOUSE_PARQUET,
    shock_ageb_output_path: str | Path = SHOCK_AGEB_PARQUET,
    gal_path: str | Path = GRAPH_GAL_PATH,
    metadata_path: Optional[str | Path] = GRAPH_METADATA_JSON,
    integrity_report: Optional[dict] = None,
    id_col: str = AGEB_ID_COL,
    sector_col: str = SECTOR_COL,
    shock_sector_col: str = DEFAULT_SECTOR_COL,
    shock_delta_col: str = DEFAULT_DELTA_COL,
    shock_col: str = DEFAULT_SHOCK_COL,
    strict_shock_alignment: bool = True,
    cond_tol: float = DEFAULT_COND_TOL,
    tol: float = 1e-6,
) -> RhoCalibrationResult:
    """
    Calibra ρ para el escenario de `resultado_simulacion` (ya calculado
    por `ModeloEconomico.simular()` / `simular_multiple()`) buscando,
    en una grilla de dos etapas (gruesa, luego fina alrededor del mejor
    punto de la gruesa), el ρ cuyo `Y = (I − ρW)^-1·S` tiene un Moran's
    I lo más parecido posible al Moran's I YA OBSERVADO en la actividad
    económica real de la región (ver docstring del módulo — esto es
    calibración por momentos, no estimación causal).

    Reutiliza exactamente el mismo patrón de `run_rho_sensitivity`:
    Stage 7 (reparto del shock) y Stage 8A (matriz espacial) se calculan
    UNA sola vez; solo `propagate()` (Stage 8B) se llama una vez por
    cada ρ evaluado.

    Nota de rendimiento (y de honestidad epistémica): los defaults
    (`n_grid_coarse=15, n_grid_fine=11` → 26 llamadas a `propagate()`)
    dan una precisión de ρ de ~0.03 — deliberadamente NO se usa una
    grilla más fina, porque esto es una calibración heurística por
    momentos, no una estimación causal de alta precisión (ver docstring
    del módulo); pedir más decimales de los que el método puede
    justificar sería fabricar una precisión que no existe. Una grilla
    de 41×41 (probada en `tests/test_rho_calibration.py`) tarda ~3× más
    sin ninguna ganancia interpretativa real.
    """
    gdf_shock, alloc_report = generate_shock_ageb_from_simulacion(
        resultado_simulacion,
        parquet_path=warehouse_parquet_path,
        output_path=shock_ageb_output_path,
        integrity_report=integrity_report,
        id_col=id_col,
        sector_col=sector_col,
        shock_sector_col=shock_sector_col,
        shock_delta_col=shock_delta_col,
        tol=tol,
        write=True,
    )
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    S, _shock_report = load_shock_vector(
        sm, parquet_path=shock_ageb_output_path, id_col=id_col, shock_col=shock_col,
        strict=strict_shock_alignment,
    )

    x_obs = observed_peso_ageb(warehouse_parquet_path, sm)
    i_obs = morans_i(x_obs, sm.W)

    def _eval_grid(rho_values: np.ndarray) -> list[dict]:
        rows = []
        for rho in rho_values:
            try:
                Y, _prop_report = propagate(sm, S, float(rho), cond_tol=cond_tol)
            except (InvalidRhoError, SingularPropagationMatrixError):
                continue
            i_y = morans_i(Y, sm.W)
            rows.append({"rho": float(rho), "morans_i_Y": i_y, "diferencia_absoluta": abs(i_y - i_obs)})
        return rows

    coarse_values = np.linspace(rho_bounds[0], rho_bounds[1], n_grid_coarse)
    coarse_rows = _eval_grid(coarse_values)

    if not coarse_rows:
        return RhoCalibrationResult(
            rho_calibrado=float("nan"), morans_i_observado=i_obs, morans_i_modelo=float("nan"),
            diferencia_absoluta=float("nan"), convergio=False, criterio_espacial=sm.criterio,
            n_agebs=len(sm.ids), n_rho_evaluados=0,
            grid=pd.DataFrame(columns=["rho", "morans_i_Y", "diferencia_absoluta"]),
        )

    best_coarse = min(coarse_rows, key=lambda r: r["diferencia_absoluta"])
    paso_coarse = (rho_bounds[1] - rho_bounds[0]) / max(n_grid_coarse - 1, 1)
    fine_lo = max(rho_bounds[0], best_coarse["rho"] - paso_coarse)
    fine_hi = min(rho_bounds[1], best_coarse["rho"] + paso_coarse)
    fine_values = np.linspace(fine_lo, fine_hi, n_grid_fine)
    fine_rows = _eval_grid(fine_values)

    all_rows = coarse_rows + fine_rows
    best = min(all_rows, key=lambda r: r["diferencia_absoluta"])

    grid_df = (
        pd.DataFrame(all_rows)
        .drop_duplicates(subset="rho")
        .sort_values("rho")
        .reset_index(drop=True)
    )

    return RhoCalibrationResult(
        rho_calibrado=best["rho"],
        morans_i_observado=i_obs,
        morans_i_modelo=best["morans_i_Y"],
        diferencia_absoluta=best["diferencia_absoluta"],
        convergio=True,
        criterio_espacial=sm.criterio,
        n_agebs=len(sm.ids),
        n_rho_evaluados=len(all_rows),
        grid=grid_df,
    )


__all__ = ["morans_i", "observed_peso_ageb", "RhoCalibrationResult", "calibrate_rho", "METODOLOGIA"]
