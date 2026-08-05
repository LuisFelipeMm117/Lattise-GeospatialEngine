# spatial/simulation/scenario.py
"""
Scenario — API de alto nivel del Spatial Econometric Engine (SEE),
Stage 8D (Especificación Formal v3.0, Sección 3 y 8).

Responsabilidad:
    Orquestar el pipeline completo

        SERIO (ModeloEconomico.simular)
            -> SERIO Bridge (generate_shock_ageb_from_simulacion)
            -> shock_ageb.parquet
            -> Operador de Propagación (load_shock_vector + propagate)
            -> Y = (I - rho*W)^-1 . S

    a partir de exactamente cuatro parámetros de usuario: estado, sector,
    monto y rho. `Scenario` es un orquestador puro: no recalcula, no
    modifica ni reconstruye ningún artefacto de los Stages 1-8C
    (CERRADOS) — consume exclusivamente sus APIs públicas ya existentes:

        - serio.loader.ModeloEconomico.simular()                    (SERIO, CERRADO)
        - spatial.allocation.serio_bridge.generate_shock_ageb_from_simulacion()
                                                                       (Stage 7, CERRADO)
        - spatial.simulation.matrix.SpatialMatrix                    (Stage 8A, CERRADO)
        - spatial.simulation.operator.load_shock_vector() / propagate()
                                                                       (Stage 8B, CERRADO)

    `modelo` (ModeloEconomico) y `sm` (SpatialMatrix) son dependencias ya
    construidas que el caller aporta a `Scenario.run()` — igual que cada
    incremento anterior del SEE, este módulo nunca instancia
    `ModeloEconomico` ni reconstruye una `SpatialMatrix` internamente
    (Layer Isolation, Sección 5).

    Ninguna resolución de `estado`/`sector` se infiere en silencio:
    valores no reconocidos por `ModeloEconomico` se rechazan explícitamente
    con `ScenarioConfigError`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd

from spatial.allocation.allocator import AllocationReport
from spatial.allocation.serio_bridge import generate_shock_ageb_from_simulacion
from spatial.config import WAREHOUSE_PARQUET
from spatial.simulation.matrix import SpatialMatrix
from spatial.simulation.operator import (
    DEFAULT_COND_TOL,
    SHOCK_AGEB_PARQUET,
    PropagationReport,
    ShockVectorReport,
    load_shock_vector,
    propagate,
)

logger = logging.getLogger("sew.simulation.scenario")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")


# ══════════════════════════════════════════════════════════════════════════
# Excepciones explícitas — nunca se infiere estado/sector desconocido
# ══════════════════════════════════════════════════════════════════════════
class ScenarioConfigError(ValueError):
    """`estado` o `sector` no resuelven a una entrada válida de ModeloEconomico."""


# ══════════════════════════════════════════════════════════════════════════
# Resolución explícita estado / sector contra ModeloEconomico
# ══════════════════════════════════════════════════════════════════════════
def _resolve_estado_key(modelo: Any, estado: str) -> str:
    """
    Acepta tanto el nombre legible (`modelo.mapa_estados`, p.ej. 'Queretaro')
    como la clave interna de carpeta (`modelo.estados_raw`, p.ej.
    'QUERETARO'). Nunca infiere una coincidencia parcial ni normaliza
    mayúsculas/acentos — rechaza explícitamente cualquier valor que no
    coincida EXACTAMENTE con uno de los dos catálogos.
    """
    if estado in modelo.mapa_estados:
        return modelo.mapa_estados[estado]
    if estado in modelo.estados_raw:
        return estado
    disponibles = sorted(modelo.mapa_estados.keys())
    raise ScenarioConfigError(
        f"estado={estado!r} no reconocido por ModeloEconomico. Usa el nombre "
        f"legible (p.ej. {disponibles[:5]}{'...' if len(disponibles) > 5 else ''}) "
        "o la clave interna de carpeta (modelo.estados_raw)."
    )


def _resolve_sector_idx(modelo: Any, sector: str) -> int:
    """
    Resuelve `sector` como código SCIAN presente en `modelo.scian_idx`
    (mismo catálogo que `modelo.sectores`). Nunca infiere el sector más
    cercano ni acepta un índice numérico posicional — rechaza
    explícitamente cualquier código no catalogado.
    """
    sector_str = str(sector)
    if sector_str in modelo.scian_idx:
        return modelo.scian_idx[sector_str]
    raise ScenarioConfigError(
        f"sector={sector!r} no es un código SCIAN reconocido por "
        f"ModeloEconomico ({modelo.n} sectores disponibles en modelo.sectores)."
    )


# ══════════════════════════════════════════════════════════════════════════
# ScenarioReport — mismo patrón que AllocationReport/ShockVectorReport/
#                  PropagationReport: to_dict()/to_json()/summary()
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class ScenarioReport:
    estado: str
    estado_key: str
    sector: str
    sector_idx: int
    sector_nombre: str
    sector_activo_en_estado: bool
    monto_pesos: float
    rho: float

    # ── SERIO (ModeloEconomico.simular) ─────────────────────────────────
    delta_X_total_pesos: float
    delta_VA_total_pesos: float
    delta_E_total: float
    mult_produccion: float
    mult_ingreso: float
    mult_empleo: float

    # ── SSD / Allocation (Stage 7) ──────────────────────────────────────
    n_sectores_shock: int
    sectores_sin_cobertura_espacial: list
    n_agebs_excluidos_por_sector: dict
    omega_sum_by_sector: dict

    # ── Shock Vector (carga de shock_ageb.parquet, Stage 8B) ───────────
    n_nodos_matrix: int
    n_agebs_en_parquet: int
    n_agebs_desconocidos: int
    agebs_desconocidos: list
    n_agebs_sin_shock: int

    # ── Propagación espacial Y = (I - rho*W)^-1 . S (Stage 8B) ─────────
    suma_S: float
    suma_Y: float
    multiplicador_espacial_global: Optional[float]
    radio_espectral_W: float
    rho_max_efectivo: float
    condicion_I_menos_rhoW: float
    criterio_contiguidad: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Scenario Report — {self.estado} ({self.estado_key}) · sector "
            f"{self.sector} '{self.sector_nombre}' · shock ${self.monto_pesos:,.0f} MXN "
            f"· rho={self.rho:.6f}",
            f"  SERIO: dX={self.delta_X_total_pesos:,.0f} MXN · "
            f"dVA={self.delta_VA_total_pesos:,.0f} MXN · "
            f"dEmpleo={self.delta_E_total:,.0f} puestos "
            f"(mult. prod={self.mult_produccion:.4f}, ingreso={self.mult_ingreso:.4f})",
        ]
        if not self.sector_activo_en_estado:
            lines.append(
                "  \u26a0 sector sin actividad registrada en el estado "
                "(impacto directo únicamente, sin encadenamientos locales)."
            )
        if self.sectores_sin_cobertura_espacial:
            lines.append(
                f"  \u26a0 sin cobertura espacial en el warehouse: "
                f"{self.sectores_sin_cobertura_espacial}"
            )
        lines.append(
            f"  SSD: {self.n_agebs_en_parquet} AGEB(s) en shock_ageb.parquet · "
            f"{self.n_agebs_sin_shock} sin shock directo (S_g = 0)"
        )
        if self.agebs_desconocidos:
            lines.append(
                f"  \u26a0 {self.n_agebs_desconocidos} AGEB(s) del parquet "
                f"ausente(s) en la SpatialMatrix: {self.agebs_desconocidos[:10]}"
            )
        lines.append(
            f"  SEE: {self.n_nodos_matrix} nodo(s) (criterio "
            f"'{self.criterio_contiguidad or 'desconocido'}') · "
            f"radio_espectral(W)={self.radio_espectral_W:.6f} · "
            f"rho_max_efectivo={self.rho_max_efectivo:.6f} · "
            f"cond(I-rho*W)={self.condicion_I_menos_rhoW:.4e}"
        )
        lines.append(f"  SUM(S)={self.suma_S:.4f}  ->  SUM(Y)={self.suma_Y:.4f}")
        if self.multiplicador_espacial_global is not None:
            lines.append(
                f"  multiplicador espacial global SUM(Y)/SUM(S) = "
                f"{self.multiplicador_espacial_global:.6f}"
            )
        else:
            lines.append("  multiplicador espacial global no definido (SUM(S) = 0).")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# ScenarioResult — artefactos completos de la ejecución + ScenarioReport
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class ScenarioResult:
    resultado_simulacion: dict
    shock_gdf: gpd.GeoDataFrame
    allocation_report: AllocationReport
    S: np.ndarray
    shock_vector_report: ShockVectorReport
    Y: np.ndarray
    propagation_report: PropagationReport
    sm: SpatialMatrix
    report: ScenarioReport

    def to_dict(self) -> dict:
        return self.report.to_dict()

    def to_json(self, path: Union[str, Path]) -> None:
        self.report.to_json(path)

    def summary(self) -> str:
        return self.report.summary()

    def s_series(self) -> pd.Series:
        """S indexado por cvegeo, en el mismo orden que `sm.ids`."""
        return pd.Series(self.S, index=self.sm.ids, name="S")

    def y_series(self) -> pd.Series:
        """Y indexado por cvegeo, en el mismo orden que `sm.ids`."""
        return pd.Series(self.Y, index=self.sm.ids, name="Y")

    def educational_report(self, **kwargs):
        """Genera el expediente educativo sin volver a ejecutar el motor.

        Los argumentos opcionales se delegan a
        ``build_educational_report`` (por ejemplo ``rho_method`` o rutas de
        artefactos específicas de un entorno). Se importa localmente para
        evitar que el contrato base de Scenario dependa de la capa de salida.
        """
        from spatial.simulation.educational_report import build_educational_report

        return build_educational_report(self, **kwargs)


# ══════════════════════════════════════════════════════════════════════════
# Scenario — objeto único de entrada del usuario: estado, sector, monto, rho
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class Scenario:
    """
    Punto de entrada único del Stage 8D. El usuario solo provee:

        estado : nombre legible (modelo.mapa_estados) o clave de carpeta
                 (modelo.estados_raw).
        sector : código SCIAN (modelo.scian_idx).
        monto  : shock de demanda final, en pesos mexicanos (MXN).
        rho    : parámetro de autocorrelación espacial exógeno, usado tal
                 cual por el operador de propagación (Stage 8B) —
                 SEE-Propagación, no SEE-Estimación.

    `run()` recibe `modelo` (ModeloEconomico) y `sm` (SpatialMatrix) como
    dependencias ya construidas por el caller y ejecuta el pipeline
    completo usando exclusivamente las APIs de los Stages 1-8C (CERRADOS).
    """
    estado: str
    sector: str
    monto: float
    rho: float

    def run(
        self,
        modelo: Any,
        sm: SpatialMatrix,
        *,
        warehouse_parquet: Union[str, Path] = WAREHOUSE_PARQUET,
        shock_ageb_output: Union[str, Path] = SHOCK_AGEB_PARQUET,
        integrity_report: Optional[dict] = None,
        strict_shock_alignment: bool = True,
        cond_tol: float = DEFAULT_COND_TOL,
    ) -> ScenarioResult:
        """
        Ejecuta el pipeline completo:

            1. `modelo.simular(estado_key, sector_idx, monto)`            (SERIO)
            2. `generate_shock_ageb_from_simulacion(...)`                  (Stage 7)
            3. `load_shock_vector(sm, parquet_path=shock_ageb_output, ...)`(Stage 8B)
            4. `propagate(sm, S, rho, cond_tol=cond_tol)`                  (Stage 8B)

        `estado` y `sector` se resuelven de forma explícita contra
        `modelo` — cualquier valor no catalogado se rechaza con
        `ScenarioConfigError` antes de tocar el pipeline numérico.

        `shock_ageb_output` siempre se escribe a disco (Explicit Data
        Contracts, Sección 5): es el mismo artefacto que consume
        `load_shock_vector()`, por lo que este método nunca pasa el
        GeoDataFrame del reparto directamente al operador de propagación.
        """
        estado_key = _resolve_estado_key(modelo, self.estado)
        sector_idx = _resolve_sector_idx(modelo, self.sector)

        d_estado = modelo._load_estado(estado_key)
        sector_activo = bool(d_estado["VA_r"][sector_idx] > 0)

        resultado_simulacion = modelo.simular(estado_key, sector_idx, self.monto)

        shock_gdf, allocation_report = generate_shock_ageb_from_simulacion(
            resultado_simulacion,
            parquet_path=warehouse_parquet,
            output_path=shock_ageb_output,
            integrity_report=integrity_report,
            write=True,
        )

        S, shock_vector_report = load_shock_vector(
            sm, parquet_path=shock_ageb_output, strict=strict_shock_alignment,
        )

        Y, propagation_report = propagate(sm, S, self.rho, cond_tol=cond_tol)

        report = ScenarioReport(
            estado=self.estado,
            estado_key=estado_key,
            sector=str(self.sector),
            sector_idx=sector_idx,
            sector_nombre=modelo.sector_names[modelo.sectores[sector_idx]],
            sector_activo_en_estado=sector_activo,
            monto_pesos=float(self.monto),
            rho=float(self.rho),
            delta_X_total_pesos=float(resultado_simulacion["delta_X_total_pesos"]),
            delta_VA_total_pesos=float(resultado_simulacion["delta_VA_total_pesos"]),
            delta_E_total=float(resultado_simulacion["delta_E_total"]),
            mult_produccion=float(resultado_simulacion["mult_produccion"]),
            mult_ingreso=float(resultado_simulacion["mult_ingreso"]),
            mult_empleo=float(resultado_simulacion["mult_empleo"]),
            n_sectores_shock=allocation_report.n_sectores_shock,
            sectores_sin_cobertura_espacial=list(allocation_report.sectores_sin_cobertura_espacial),
            n_agebs_excluidos_por_sector=dict(allocation_report.n_agebs_excluidos_por_sector),
            omega_sum_by_sector=dict(allocation_report.omega_sum_by_sector),
            n_nodos_matrix=shock_vector_report.n_nodos_matrix,
            n_agebs_en_parquet=shock_vector_report.n_agebs_en_parquet,
            n_agebs_desconocidos=shock_vector_report.n_agebs_desconocidos,
            agebs_desconocidos=list(shock_vector_report.agebs_desconocidos),
            n_agebs_sin_shock=shock_vector_report.n_agebs_sin_shock,
            suma_S=propagation_report.suma_S,
            suma_Y=propagation_report.suma_Y,
            multiplicador_espacial_global=propagation_report.multiplicador_global,
            radio_espectral_W=propagation_report.radio_espectral_W,
            rho_max_efectivo=propagation_report.rho_max_efectivo,
            condicion_I_menos_rhoW=propagation_report.condicion_I_menos_rhoW,
            criterio_contiguidad=sm.criterio,
        )
        logger.info("\n%s", report.summary())

        return ScenarioResult(
            resultado_simulacion=resultado_simulacion,
            shock_gdf=shock_gdf,
            allocation_report=allocation_report,
            S=S,
            shock_vector_report=shock_vector_report,
            Y=Y,
            propagation_report=propagation_report,
            sm=sm,
            report=report,
        )


__all__ = [
    "ScenarioConfigError",
    "ScenarioReport",
    "ScenarioResult",
    "Scenario",
]
