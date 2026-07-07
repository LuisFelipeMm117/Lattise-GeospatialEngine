# spatial/simulation/operator.py
"""
Operator — Propagación espacial (Especificación Formal v3.0, Sección 3 y 8,
Stage 8 — Spatial Econometric Engine / SEE).

Responsabilidad (Incremento 2, "Stage 8B"):
    Implementar EXCLUSIVAMENTE el operador matemático de propagación
    espacial

        Y = (I − ρW)^-1 · S

    combinando dos artefactos ya persistidos y CERRADOS:
        - W : `spatial.simulation.matrix.SpatialMatrix` (Stage 8A — matriz
              espacial fila-estandarizada reconstruida desde `graph.gal`).
        - S : `shock_ageb.parquet` (Stage 7 — Spatial Shock Distributor),
              agregado a nivel AGEB (S_g = Σ_s shock_ageb_{g,s}) para
              producir el "Choque Territorial Directo" S de dimensión
              |G| × 1 que define la Sección 3 de la especificación formal
              (ΔX → [W ⊗ ω] → S → [Modelo Espacial (M)] → Y).

Este módulo:
    - NO recalcula W — consume la `SpatialMatrix` ya construida por Stage
      8A (CERRADO). No invoca `SpatialGraphBuilder` ni reconstruye
      geometrías AGEB.
    - NO recalcula ω_{g,s} ni el reparto de Stage 7 — es un consumidor
      puro de `shock_ageb.parquet` tal como lo serializa
      `spatial.allocation.allocator.generate_shock_ageb()` (CERRADO).
    - NO implementa estimación econométrica (SAR/SEM/SDM/Tobanche) — eso
      pertenece a `spatial.allocation.simulation.run_spatial_model()`
      (PENDIENTE, Phase 3, bloqueado por datos de panel DENUE) y permanece
      intacto: este módulo es únicamente el operador de propagación
      determinista, no un modelo econométrico estimado.
    - Reporta explícitamente cualquier inconsistencia entre S y W (AGEBs
      del shock ausentes en la matriz espacial) — nunca los descarta en
      silencio ni infiere una posición territorial para ellos.
    - Nunca invierte (I − ρW) sin antes validar que ρ está en un rango
      matemáticamente admisible para esta W en particular y que la matriz
      resultante no es singular ni numéricamente mal condicionada.

Depende de (solo como consumidor de sus artefactos, no como caller):
    - spatial.simulation.matrix.SpatialMatrix                (Stage 8A — CERRADO)
    - shock_ageb.parquet, producido por
      spatial.allocation.allocator.generate_shock_ageb()      (Stage 7  — CERRADO)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union

import numpy as np
import pandas as pd

from spatial.config import SSD_DIR
from spatial.simulation.matrix import SpatialMatrix

logger = logging.getLogger("sew.simulation.operator")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

SHOCK_AGEB_PARQUET = SSD_DIR / "shock_ageb.parquet"
DEFAULT_SHOCK_COL = "shock_ageb"

# ── Rango teórico admisible de ρ ─────────────────────────────────────────
# W es fila-estandarizada (Stage 8A): toda fila no-isla suma exactamente 1.
# Por Perron-Frobenius, la submatriz estocástica de nodos no-isla tiene
# radio espectral 1 (islas aportan filas nulas, nunca aumentan el radio).
# (-1, 1) es además el rango citado en la literatura de econometría
# espacial (Anselin, 1988) para modelos SAR/SEM sobre matrices de pesos
# fila-estandarizadas. Este módulo NUNCA asume 1.0 en silencio: siempre
# calcula el radio espectral real de la W recibida (`spectral_radius`) y
# deriva de él el límite EFECTIVO, potencialmente más estricto que este
# límite ABSOLUTO si el caller aporta una W no-canónica.
RHO_ABS_BOUND = 1.0

# Tolerancia por defecto para declarar (I − ρW) numéricamente singular.
DEFAULT_COND_TOL = 1e12


# ══════════════════════════════════════════════════════════════════════════
# Excepciones explícitas — nunca se silencia una inconsistencia matemática
# ══════════════════════════════════════════════════════════════════════════
class InvalidRhoError(ValueError):
    """ρ está fuera del rango matemáticamente admisible para esta W."""


class SingularPropagationMatrixError(ValueError):
    """(I − ρW) es singular, o numéricamente indistinguible de singular."""


class ShockAlignmentError(ValueError):
    """S referencia AGEB(s) ausente(s) en la SpatialMatrix (W), o viceversa, sin resolución explícita del caller."""


# ══════════════════════════════════════════════════════════════════════════
# Radio espectral de W — nunca se asume 1.0, siempre se calcula
# ══════════════════════════════════════════════════════════════════════════
def spectral_radius(W: np.ndarray) -> float:
    """
    Radio espectral de W: max(|λ_i|) sobre los autovalores de W.

    Para la W fila-estandarizada de `SpatialMatrix` (Stage 8A) este valor
    es ≤ 1 por construcción (Perron-Frobenius sobre la submatriz
    estocástica de nodos no-isla), pero se calcula explícitamente en vez
    de asumirlo, para cubrir tanto el caso trivial W = 0 (todos los nodos
    son islas → radio 0) como cualquier W no-canónica que el caller
    aporte directamente a `propagate()`.
    """
    n = W.shape[0] if W.ndim == 2 else 0
    if n == 0:
        return 0.0
    eigvals = np.linalg.eigvals(W)
    return float(np.max(np.abs(eigvals)))


def validate_rho(rho: float, radio_espectral: float) -> None:
    """
    Valida que ρ esté en el rango matemáticamente admisible:
      1. |ρ| < 1 — límite ABSOLUTO teórico (Anselin, 1988) para cualquier
         matriz de pesos espaciales fila-estandarizada.
      2. |ρ| < 1 / radio_espectral(W) — límite EFECTIVO, específico de la
         W en particular; se salta únicamente si `radio_espectral == 0`
         (W nula: (I − ρW) = I siempre, para cualquier ρ finito).

    Nunca infiere ni redondea ρ: rechaza explícitamente con
    `InvalidRhoError` ante cualquier valor fuera de rango, no finito, o
    no numérico.
    """
    try:
        rho_val = float(rho)
    except (TypeError, ValueError) as exc:
        raise InvalidRhoError(f"ρ={rho!r} no es un valor numérico válido.") from exc

    if not np.isfinite(rho_val):
        raise InvalidRhoError(f"ρ={rho_val} no es finito (NaN/Inf no admitidos).")

    if abs(rho_val) >= RHO_ABS_BOUND:
        raise InvalidRhoError(
            f"ρ={rho_val} está fuera del rango teórico abierto (-1, 1) admitido "
            "para una matriz de pesos espaciales fila-estandarizada (Anselin, 1988)."
        )

    if radio_espectral > 0.0:
        limite_efectivo = 1.0 / radio_espectral
        if abs(rho_val) >= limite_efectivo:
            raise InvalidRhoError(
                f"ρ={rho_val} excede el límite efectivo 1/radio_espectral(W)="
                f"{limite_efectivo:.6f} (radio_espectral(W)={radio_espectral:.6f}); "
                "(I − ρW) sería singular o numéricamente inestable para esta W."
            )


# ══════════════════════════════════════════════════════════════════════════
# Reporte de alineación S ↔ W (carga de shock_ageb.parquet)
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class ShockVectorReport:
    n_nodos_matrix: int
    n_agebs_en_parquet: int
    n_agebs_desconocidos: int = 0
    agebs_desconocidos: list = field(default_factory=list)
    n_agebs_sin_shock: int = 0
    suma_shock_total: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Shock Vector Report — {self.n_agebs_en_parquet} AGEB(s) en el parquet, "
            f"{self.n_nodos_matrix} nodo(s) en la SpatialMatrix",
            f"  ΣS (shock territorial total) = {self.suma_shock_total:.4f}",
            f"  {self.n_agebs_sin_shock} AGEB(s) de la matriz sin shock asignado (S_g = 0)",
        ]
        if self.agebs_desconocidos:
            lines.append(
                f"  ⚠ {self.n_agebs_desconocidos} AGEB(s) del parquet ausente(s) en la "
                f"SpatialMatrix (excluidos explícitamente): {self.agebs_desconocidos[:10]}"
            )
        else:
            lines.append("  todos los AGEBs del parquet pertenecen a la SpatialMatrix.")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Carga de S — consumidor puro de shock_ageb.parquet (Stage 7, CERRADO)
# ══════════════════════════════════════════════════════════════════════════
def load_shock_vector(
    sm: SpatialMatrix,
    parquet_path: Union[str, Path] = SHOCK_AGEB_PARQUET,
    id_col: Optional[str] = None,
    shock_col: str = DEFAULT_SHOCK_COL,
    strict: bool = True,
) -> tuple[np.ndarray, ShockVectorReport]:
    """
    Construye S (Choque Territorial Directo, |G| × 1) a partir de
    `shock_ageb.parquet`, alineado EXACTAMENTE con `sm.ids` (mismo orden
    que las filas/columnas de W).

    Como `shock_ageb.parquet` tiene una fila por par (AGEB, sector)
    (`shock_ageb_{g,s} = ω_{g,s} · ΔX_s`, Stage 7), y la Sección 3 de la
    especificación define S como un vector puramente geográfico (|G| × 1,
    sin dimensión sectorial), este loader agrega explícitamente:

        S_g = Σ_s shock_ageb_{g,s}

    AGEBs de la SpatialMatrix sin ninguna fila en el parquet reciben
    S_g = 0 (ausencia de shock, no ausencia de dato — un AGEB puede
    legítimamente no recibir choque directo). AGEBs presentes en el
    parquet pero AUSENTES en la SpatialMatrix son una inconsistencia
    estructural real entre Stage 7 y el Spatial Graph:
      - `strict=True` (default): se rechaza con `ShockAlignmentError`,
        listando los AGEBs desconocidos — nunca se descartan en silencio.
      - `strict=False`: se excluyen explícitamente de S y quedan
        registrados en `ShockVectorReport.agebs_desconocidos`.
    """
    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"No se encontró '{parquet_path}'. Ejecuta "
            "spatial.allocation.allocator.generate_shock_ageb() (Stage 7) primero."
        )

    id_col = id_col or sm.id_col

    df = pd.read_parquet(parquet_path)
    faltantes_cols = [c for c in (id_col, shock_col) if c not in df.columns]
    if faltantes_cols:
        raise ValueError(
            f"'{parquet_path}' no tiene la(s) columna(s) {faltantes_cols} esperada(s) "
            "de shock_ageb.parquet (Stage 7, allocation.allocator.allocate_shock())."
        )

    shock_por_ageb = df.groupby(id_col)[shock_col].sum()

    ids_shock = set(shock_por_ageb.index)
    ids_matrix = set(sm.ids)
    desconocidos = sorted(str(cvegeo) for cvegeo in (ids_shock - ids_matrix))

    if desconocidos and strict:
        raise ShockAlignmentError(
            f"'{parquet_path}' contiene {len(desconocidos)} AGEB(s) ausente(s) en la "
            f"SpatialMatrix (Stage 8A): {desconocidos[:10]}"
            + (" ..." if len(desconocidos) > 10 else "")
            + ". Reconstruye W con SpatialMatrix.from_gal() sobre el mismo universo de "
            "AGEBs que shock_ageb.parquet, o llama con strict=False para excluirlos "
            "explícitamente del vector S."
        )

    if desconocidos:
        shock_por_ageb = shock_por_ageb.drop(index=list(ids_shock - ids_matrix))

    S = shock_por_ageb.reindex(sm.ids, fill_value=0.0).to_numpy(dtype=np.float64)

    report = ShockVectorReport(
        n_nodos_matrix=len(sm.ids),
        n_agebs_en_parquet=len(ids_shock),
        n_agebs_desconocidos=len(desconocidos),
        agebs_desconocidos=desconocidos,
        n_agebs_sin_shock=int(np.sum(S == 0.0)),
        suma_shock_total=float(S.sum()),
    )
    logger.info("\n%s", report.summary())
    return S, report


# ══════════════════════════════════════════════════════════════════════════
# Reporte de propagación — mismo patrón que SpatialMatrixReport/AllocationReport
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class PropagationReport:
    n_nodos: int
    rho: float
    radio_espectral_W: float
    rho_max_efectivo: float
    condicion_I_menos_rhoW: float
    metodo: str
    suma_S: float
    suma_Y: float
    multiplicador_global: Optional[float]
    n_agebs_con_shock: int
    criterio: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        criterio_txt = self.criterio if self.criterio is not None else "desconocido"
        lines = [
            f"Propagation Report — {self.n_nodos} nodos, ρ={self.rho:.6f} "
            f"(criterio '{criterio_txt}')",
            f"  radio_espectral(W)={self.radio_espectral_W:.6f}  →  "
            f"ρ máximo efectivo admitido={self.rho_max_efectivo:.6f}",
            f"  cond(I − ρW)={self.condicion_I_menos_rhoW:.4e}  ·  método: {self.metodo}",
            f"  ΣS={self.suma_S:.4f}  →  ΣY={self.suma_Y:.4f}  "
            f"({self.n_agebs_con_shock} AGEB(s) con shock directo != 0)",
        ]
        if self.multiplicador_global is not None:
            lines.append(f"  multiplicador global ΣY/ΣS = {self.multiplicador_global:.6f}")
        else:
            lines.append("  multiplicador global no definido (ΣS = 0).")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Operador — Y = (I − ρW)^-1 · S, resuelto como sistema lineal
# ══════════════════════════════════════════════════════════════════════════
def _align_series_to_ids(S: pd.Series, ids: list) -> np.ndarray:
    faltantes = [cvegeo for cvegeo in ids if cvegeo not in S.index]
    if faltantes:
        raise ShockAlignmentError(
            f"S (pd.Series) no tiene entrada para {len(faltantes)} AGEB(s) de la "
            f"SpatialMatrix: {faltantes[:10]}"
            + (" ..." if len(faltantes) > 10 else "")
            + ". S debe cubrir la totalidad de sm.ids — usa fill_value=0.0 explícito "
            "en el caller si un AGEB legítimamente no tiene shock."
        )
    return S.reindex(ids).to_numpy(dtype=np.float64)


def propagate(
    sm: SpatialMatrix,
    S: Union[np.ndarray, pd.Series, Sequence[float]],
    rho: float,
    cond_tol: float = DEFAULT_COND_TOL,
) -> tuple[np.ndarray, PropagationReport]:
    """
    Calcula Y = (I − ρW)^-1 · S (Sección 3 de la especificación formal),
    resolviendo el sistema lineal (I − ρW) Y = S en vez de invertir
    explícitamente (equivalente algebraico, más estable numéricamente).

    Alineación de S:
      - `np.ndarray` / secuencia: se asume YA alineada posicionalmente con
        `sm.ids` (mismo orden); se valida únicamente la longitud.
      - `pd.Series`: se re-alinea EXPLÍCITAMENTE por índice (`cvegeo`) a
        `sm.ids`, nunca por posición cruda de la Series. Usa
        `load_shock_vector(sm, ...)` para construir S directamente desde
        `shock_ageb.parquet` con esta garantía.

    Validaciones matemáticas (en este orden, todas antes de tocar la
    inversión):
      1. Forma y finitud de S.
      2. Rango admisible de ρ (`validate_rho`, usando el radio espectral
         real de `sm.W`, nunca asumido).
      3. Condición numérica de (I − ρW): si `cond(I − ρW) > cond_tol` o la
         factorización falla, se rechaza con
         `SingularPropagationMatrixError` — nunca se devuelve un resultado
         construido sobre una inversión inestable o indefinida.

    Para ρ = 0, (I − ρW) = I exactamente, por lo que Y = S (identidad),
    verificado explícitamente en `tests/test_operator.py`.
    """
    n = len(sm.ids)

    if isinstance(S, pd.Series):
        S_arr = _align_series_to_ids(S, sm.ids)
    else:
        S_arr = np.asarray(S, dtype=np.float64)

    if S_arr.ndim != 1 or S_arr.shape[0] != n:
        raise ValueError(
            f"S tiene forma {S_arr.shape}; se esperaba un vector de longitud {n} "
            "(= len(sm.ids), el mismo orden de filas/columnas de W)."
        )
    if not np.all(np.isfinite(S_arr)):
        raise ValueError("S contiene valores no finitos (NaN/Inf) — corrígelos antes de propagar.")

    W = sm.W
    radio_espectral = spectral_radius(W)
    validate_rho(rho, radio_espectral)
    rho_val = float(rho)

    I = np.eye(n)
    M = I - rho_val * W

    cond = float(np.linalg.cond(M))
    if not np.isfinite(cond) or cond > cond_tol:
        raise SingularPropagationMatrixError(
            f"(I − ρW) está singular o mal condicionada para ρ={rho_val} "
            f"(cond={cond:.4e} > tolerancia {cond_tol:.1e}). Reduce |ρ| o revisa la "
            "conectividad de W (componentes desconectados, nodos casi-aislados)."
        )

    try:
        Y = np.linalg.solve(M, S_arr)
    except np.linalg.LinAlgError as exc:
        raise SingularPropagationMatrixError(
            f"(I − ρW) resultó numéricamente singular al resolver para ρ={rho_val}: {exc}"
        ) from exc

    suma_S = float(S_arr.sum())
    suma_Y = float(Y.sum())
    mult_global = (suma_Y / suma_S) if abs(suma_S) > 1e-12 else None
    rho_max_efectivo = (1.0 / radio_espectral) if radio_espectral > 0.0 else float("inf")

    report = PropagationReport(
        n_nodos=n,
        rho=rho_val,
        radio_espectral_W=radio_espectral,
        rho_max_efectivo=rho_max_efectivo,
        condicion_I_menos_rhoW=cond,
        metodo="solve_directo: (I - rho*W) @ Y = S",
        suma_S=suma_S,
        suma_Y=suma_Y,
        multiplicador_global=mult_global,
        n_agebs_con_shock=int(np.sum(S_arr != 0.0)),
        criterio=sm.criterio,
    )
    logger.info("\n%s", report.summary())
    return Y, report


# ══════════════════════════════════════════════════════════════════════════
# Serie de Neumann — ÚNICAMENTE como prueba de convergencia independiente
# ══════════════════════════════════════════════════════════════════════════
def neumann_series_sum(
    W: np.ndarray,
    rho: float,
    S: Union[np.ndarray, Sequence[float]],
    max_terms: int = 200,
    tol: float = 1e-10,
) -> tuple[np.ndarray, int, bool]:
    """
    Aproxima Y = (I − ρW)^-1 · S mediante la serie de Neumann

        Y ≈ Σ_{k=0}^{K} ρ^k W^k S

    ÚNICAMENTE como verificación de convergencia independiente de
    `propagate()` (que siempre resuelve el sistema lineal exacto vía
    `np.linalg.solve` — este no es el camino de producción). La serie
    converge si y solo si |ρ| · radio_espectral(W) < 1 (condición estándar
    de convergencia de Neumann para el operador (I − ρW)^-1); esa es
    exactamente la condición que `validate_rho()` exige para aceptar ρ,
    por lo que cualquier ρ válido para `propagate()` es también válido
    para esta serie.

    Devuelve `(Y_aproximado, n_terminos_usados, convergio)`, donde
    `convergio` es `True` si la norma-infinito del término k-ésimo cayó
    por debajo de `tol` antes de agotar `max_terms`.
    """
    S_arr = np.asarray(S, dtype=np.float64)
    termino = S_arr.copy()
    Y_approx = S_arr.copy()
    convergio = False
    n_usados = 0

    for k in range(1, max_terms + 1):
        termino = rho * (W @ termino)
        Y_approx = Y_approx + termino
        n_usados = k
        if np.max(np.abs(termino)) < tol:
            convergio = True
            break

    return Y_approx, n_usados, convergio


__all__ = [
    "RHO_ABS_BOUND",
    "DEFAULT_COND_TOL",
    "SHOCK_AGEB_PARQUET",
    "InvalidRhoError",
    "SingularPropagationMatrixError",
    "ShockAlignmentError",
    "ShockVectorReport",
    "PropagationReport",
    "spectral_radius",
    "validate_rho",
    "load_shock_vector",
    "propagate",
    "neumann_series_sum",
]