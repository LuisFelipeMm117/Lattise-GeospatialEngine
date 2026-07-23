# spatial/simulation/engine.py
"""
Simulation Engine — Orquestación end-to-end del Spatial Econometric Engine
(Especificación Formal v3.0, Sección 8, Stage 8C).

Responsabilidad (Incremento 3, "Stage 8C"):
    Orquestar, sin recalcular ninguna etapa anterior, la secuencia completa

        ModeloEconomico.simular()
            ↓
        generate_shock_ageb_from_simulacion()   (Stage 7 — Bridge, CERRADO)
            ↓
        SpatialMatrix.from_gal()                (Stage 8A — CERRADO)
            ↓
        load_shock_vector()                     (Stage 8B — CERRADO)
            ↓
        propagate()                             (Stage 8B — CERRADO)
            ↓
        GeoDataFrame propagado + SimulationReport

    que la Sección 3 de la especificación formal resume como
    ΔX → [W ⊗ ω] → S → [Modelo Espacial (M)] → Y.

Este módulo:
    - NO reconstruye `warehouse.parquet` — es un consumidor puro, igual que
      `spatial.allocation.serio_bridge` (Stage 7, CERRADO).
    - NO reconstruye `graph.gal`/`graph_metadata.json` — es un consumidor
      puro, igual que `spatial.simulation.matrix` (Stage 8A, CERRADO).
    - NO reparte shocks manualmente ni reimplementa ω_{g,s} — delega
      íntegramente en `generate_shock_ageb_from_simulacion()` (Stage 7).
    - NO reimplementa `(I − ρW)^-1` — delega íntegramente en
      `spatial.simulation.operator.propagate()` (Stage 8B).
    - Su única responsabilidad propia es encadenar las llamadas en el
      orden correcto, ensamblar el `GeoDataFrame` final (geometría +
      choque directo + impacto propagado) y producir un
      `SimulationReport` de trazabilidad de extremo a extremo — mismo
      patrón `to_dict()`/`to_json()`/`summary()` que el resto del SEW.
    - Reporta explícitamente cualquier inconsistencia que ya hayan
      detectado las etapas subyacentes (`AllocationReport`,
      `ShockVectorReport`, `PropagationReport`) — nunca las oculta ni las
      recalcula, solo las embebe en `SimulationReport.to_dict()`.

Depende de (solo como consumidor de sus APIs, no como caller de sus
etapas internas):
    - spatial.allocation.serio_bridge.generate_shock_ageb_from_simulacion  (Stage 7 — CERRADO)
    - spatial.simulation.matrix.SpatialMatrix.from_gal                     (Stage 8A — CERRADO)
    - spatial.simulation.operator.load_shock_vector / propagate            (Stage 8B — CERRADO)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from spatial.allocation.allocator import AllocationReport
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
    PropagationReport,
    ShockVectorReport,
    SingularPropagationMatrixError,
    load_shock_vector,
    propagate,
    spectral_radius,
)
from spatial.warehouse.builder import SECTOR_COL

logger = logging.getLogger("sew.simulation.engine")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

IMPACTO_DIRECTO_COL = "shock_directo"
IMPACTO_PROPAGADO_COL = "impacto_propagado"
IMPACTO_INDIRECTO_COL = "impacto_indirecto"


# ══════════════════════════════════════════════════════════════════════════
# Reporte de extremo a extremo — mismo patrón que Allocation/Matrix/Propagation
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SimulationReport:
    """
    Trazabilidad completa de una corrida del Simulation Engine (Stage 8C):
    parámetros del modelo espacial, magnitudes agregadas del choque antes y
    después de propagar, artefactos consumidos/producidos, y los reportes
    íntegros (`to_dict()`) de cada etapa subyacente — sin recalcular nada
    de lo que esas etapas ya reportaron.
    """
    rho: float
    n_agebs: int
    n_sectores: int
    shock_total_inicial: float
    shock_total_propagado: float
    multiplicador_global: Optional[float]
    tiempo_ejecucion_seg: float
    criterio: Optional[str] = None
    ruta_warehouse_parquet: str = ""
    ruta_shock_ageb_parquet: str = ""
    ruta_graph_gal: str = ""
    ruta_graph_metadata: Optional[str] = None
    sectores_sin_cobertura_espacial: list = field(default_factory=list)
    agebs_desconocidos_en_shock: list = field(default_factory=list)
    allocation_report: dict = field(default_factory=dict)
    shock_vector_report: dict = field(default_factory=dict)
    propagation_report: dict = field(default_factory=dict)
    spatial_matrix_report: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        criterio_txt = self.criterio if self.criterio is not None else "desconocido"
        lines = [
            f"Simulation Engine Report — {self.n_agebs} AGEB(s), {self.n_sectores} sector(es) "
            f"en el shock, ρ={self.rho:.6f} (criterio '{criterio_txt}')",
            f"  ΣS (choque territorial)={self.shock_total_inicial:.4f}  →  "
            f"ΣY (impacto propagado)={self.shock_total_propagado:.4f}",
            f"  tiempo de ejecución: {self.tiempo_ejecucion_seg:.4f} s",
        ]
        if self.multiplicador_global is not None:
            lines.append(f"  multiplicador global ΣY/ΣS = {self.multiplicador_global:.6f}")
        else:
            lines.append("  multiplicador global no definido (ΣS = 0).")
        if self.sectores_sin_cobertura_espacial:
            lines.append(
                f"  ⚠ sectores sin cobertura espacial (excluidos del reparto): "
                f"{self.sectores_sin_cobertura_espacial}"
            )
        if self.agebs_desconocidos_en_shock:
            lines.append(
                f"  ⚠ {len(self.agebs_desconocidos_en_shock)} AGEB(s) del shock ausente(s) "
                f"en la SpatialMatrix: {self.agebs_desconocidos_en_shock[:10]}"
            )
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Ensamblado del GeoDataFrame final — geometría (Stage 7) + S y Y (Stage 8B)
# ══════════════════════════════════════════════════════════════════════════
def _build_result_geodataframe(
    sm: SpatialMatrix,
    gdf_shock: gpd.GeoDataFrame,
    S: np.ndarray,
    Y: np.ndarray,
    id_col: str,
) -> gpd.GeoDataFrame:
    """
    Ensambla el `GeoDataFrame` final: una fila por AGEB de la
    `SpatialMatrix` (mismo orden que `sm.ids`), con su geometría tomada
    de `gdf_shock` (ya la trae Stage 7, sin releer `warehouse.parquet`),
    el choque territorial directo `S`, el impacto propagado `Y`, y el
    impacto indirecto `Y - S` derivado por diferencia (no recalculado).

    AGEBs de `sm.ids` ausentes en `gdf_shock` (nunca recibieron ningún
    reparto de ω, en ningún sector) reciben `geometry = None` — nunca se
    infiere ni interpola una geometría.
    """
    geom_dedup = (
        gdf_shock[[id_col, "geometry"]]
        .drop_duplicates(subset=[id_col])
        .set_index(id_col)["geometry"]
    )

    df = pd.DataFrame({
        id_col: sm.ids,
        IMPACTO_DIRECTO_COL: S,
        IMPACTO_PROPAGADO_COL: Y,
        IMPACTO_INDIRECTO_COL: Y - S,
        "es_isla": [sm.is_island(cvegeo) for cvegeo in sm.ids],
    })
    df["geometry"] = df[id_col].map(geom_dedup)

    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=gdf_shock.crs)
    return gdf


# ══════════════════════════════════════════════════════════════════════════
# Orquestación completa — Stage 8C
# ══════════════════════════════════════════════════════════════════════════
def run_simulation_engine(
    resultado_simulacion: Mapping[str, Any],
    rho: float,
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
) -> tuple[gpd.GeoDataFrame, SimulationReport]:
    """
    Pipeline completo del Simulation Engine (Stage 8C):

        ModeloEconomico.simular() [ya ejecutado por el caller, `resultado_simulacion`]
            → generate_shock_ageb_from_simulacion()   (Stage 7, CERRADO)
            → SpatialMatrix.from_gal()                (Stage 8A, CERRADO)
            → load_shock_vector()                     (Stage 8B, CERRADO)
            → propagate()                             (Stage 8B, CERRADO)
            → GeoDataFrame final + SimulationReport

    No recalcula `warehouse.parquet` ni `graph.gal` — ambos se leen tal
    cual de `warehouse_parquet_path` / `gal_path` (artefactos ya cerrados
    de Stage 5 y del Spatial Graph Builder). No reparte shocks
    manualmente: todo el reparto ω_{g,s} lo produce
    `generate_shock_ageb_from_simulacion()` (Stage 7).

    Parámetros
    ----------
    resultado_simulacion : dict devuelto por `ModeloEconomico.simular()`
        (`serio/loader.py`) — debe contener la clave `df_detalle` con las
        columnas `shock_sector_col` y `shock_delta_col`.
    rho : ρ del modelo espacial `(I − ρW)^-1`, validado internamente por
        `propagate()` contra el radio espectral real de W.
    warehouse_parquet_path, gal_path, metadata_path : rutas de los
        artefactos YA CERRADOS que este incremento únicamente consume.
    shock_ageb_output_path : ruta donde se serializa `shock_ageb.parquet`
        (Stage 7) — se persiste siempre, porque `load_shock_vector()`
        (Stage 8B) es un consumidor puro del artefacto en disco, no del
        `GeoDataFrame` en memoria.
    strict_shock_alignment : ver `operator.load_shock_vector(strict=...)`.

    Devuelve
    --------
    (gdf_final, report) : `GeoDataFrame` con una fila por AGEB de la
    `SpatialMatrix` (geometría + `shock_directo` + `impacto_propagado` +
    `impacto_indirecto`) y el `SimulationReport` de trazabilidad completa.
    """
    t0 = time.perf_counter()

    # ── 1. ModeloEconomico.simular() → shock_ageb.parquet (Stage 7, CERRADO) ──
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

    # ── 2. graph.gal → SpatialMatrix (Stage 8A, CERRADO) ──────────────────
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    # ── 3. shock_ageb.parquet → S alineado a sm.ids (Stage 8B, CERRADO) ───
    S, shock_report = load_shock_vector(
        sm,
        parquet_path=shock_ageb_output_path,
        id_col=id_col,
        shock_col=shock_col,
        strict=strict_shock_alignment,
    )

    # ── 4. Y = (I − ρW)^-1 · S (Stage 8B, CERRADO) ────────────────────────
    Y, prop_report = propagate(sm, S, rho, cond_tol=cond_tol)

    # ── 5. Ensamblado del GeoDataFrame final ──────────────────────────────
    gdf_final = _build_result_geodataframe(sm, gdf_shock, S, Y, id_col=id_col)

    tiempo_ejecucion = time.perf_counter() - t0

    n_sectores = int(pd.Series(resultado_simulacion["df_detalle"][shock_sector_col]).nunique())

    report = SimulationReport(
        rho=prop_report.rho,
        n_agebs=len(sm.ids),
        n_sectores=n_sectores,
        shock_total_inicial=prop_report.suma_S,
        shock_total_propagado=prop_report.suma_Y,
        multiplicador_global=prop_report.multiplicador_global,
        tiempo_ejecucion_seg=tiempo_ejecucion,
        criterio=sm.criterio,
        ruta_warehouse_parquet=str(Path(warehouse_parquet_path)),
        ruta_shock_ageb_parquet=str(Path(shock_ageb_output_path)),
        ruta_graph_gal=str(Path(gal_path)),
        ruta_graph_metadata=str(Path(metadata_path)) if metadata_path is not None else None,
        sectores_sin_cobertura_espacial=list(alloc_report.sectores_sin_cobertura_espacial),
        agebs_desconocidos_en_shock=list(shock_report.agebs_desconocidos),
        allocation_report=alloc_report.to_dict(),
        shock_vector_report=shock_report.to_dict(),
        propagation_report=prop_report.to_dict(),
        spatial_matrix_report=sm.report.to_dict(),
    )
    logger.info("\n%s", report.summary())

    return gdf_final, report


# ══════════════════════════════════════════════════════════════════════════
# Análisis de sensibilidad — Fase 5 (GIS Workstation)
# ══════════════════════════════════════════════════════════════════════════
def run_rho_sensitivity(
    resultado_simulacion: Mapping[str, Any],
    rho_values: list[float],
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
) -> tuple[pd.DataFrame, dict]:
    """
    Corre el MISMO escenario (mismo `resultado_simulacion`, mismo shock S)
    a través de varios valores de ρ, para responder "¿qué tan sensible es
    el resultado a mi supuesto de decaimiento espacial?" — sin volver a
    calcular Stage 7 (SSD) una vez por cada ρ.

        ModeloEconomico.simular() [ya ejecutado por el caller]
            → generate_shock_ageb_from_simulacion()   (Stage 7, CERRADO) — UNA vez
            → SpatialMatrix.from_gal()                (Stage 8A, CERRADO) — UNA vez
            → load_shock_vector()                     (Stage 8B, CERRADO) — UNA vez
            → propagate()                             (Stage 8B, CERRADO) — UNA vez POR ρ
            → tabla (ρ, ΣS, ΣY, multiplicador) + metadatos del barrido

    Por qué esto es correcto (no una aproximación): S (Stage 7) y W
    (Stage 8A) NO dependen de ρ — solo el operador `(I − ρW)^-1` lo
    hace. Recalcularlos una vez por ρ (como haría llamar a
    `run_simulation_engine()` en un loop) sería redundante, no más
    correcto — este incremento reordena el trabajo, no inventa
    matemática nueva. `propagate()` en sí no se toca ni se reimplementa
    aquí: se sigue llamando tal cual, una vez por valor de ρ.

    Valores de ρ inválidos (fuera de `(-1, 1)` o del límite efectivo
    `1/radio_espectral(W)`) o que produzcan una `(I − ρW)` mal
    condicionada NO abortan todo el barrido — se omiten de la tabla y
    se reportan en `meta["errores"]`, para que la UI pueda mostrar
    "estos valores de ρ no son válidos para esta W" en vez de tronar.

    Parámetros
    ----------
    resultado_simulacion, warehouse_parquet_path, shock_ageb_output_path,
    gal_path, metadata_path, integrity_report, id_col, sector_col,
    shock_sector_col, shock_delta_col, shock_col, strict_shock_alignment,
    cond_tol, tol : idénticos a `run_simulation_engine()` — mismos
        nombres, mismos defaults, mismo significado.
    rho_values : lista de ρ a evaluar, en cualquier orden.

    Devuelve
    --------
    (df_sensibilidad, meta) :
        `df_sensibilidad` — un DataFrame con una fila por ρ VÁLIDO
        evaluado, columnas `rho`, `suma_S`, `suma_Y`,
        `multiplicador_global` (NaN cuando ΣS=0 y el multiplicador no
        está definido — nunca `None`, para que la columna se mantenga
        `float64` en pandas/Plotly sin casos especiales río abajo),
        `condicion_I_menos_rhoW`, ordenado por `rho` ascendente.
        `meta` — dict con `radio_espectral_W`, `rho_max_efectivo`,
        `criterio`, `n_rho_evaluados`, `n_rho_invalidos`, `errores`
        (lista de `{"rho": ..., "error": ...}` para cada ρ omitido).
    """
    # ── 1-3: idéntico a run_simulation_engine(), UNA sola vez ──────────────
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
    S, shock_report = load_shock_vector(
        sm,
        parquet_path=shock_ageb_output_path,
        id_col=id_col,
        shock_col=shock_col,
        strict=strict_shock_alignment,
    )

    radio_espectral = spectral_radius(sm.W)
    rho_max_efectivo = (1.0 / radio_espectral) if radio_espectral > 0.0 else float("inf")

    filas = []
    errores = []
    for rho in rho_values:
        try:
            _Y, prop_report = propagate(sm, S, rho, cond_tol=cond_tol)
        except (InvalidRhoError, SingularPropagationMatrixError) as exc:
            errores.append({"rho": float(rho), "error": str(exc)})
            continue
        filas.append({
            "rho": prop_report.rho,
            "suma_S": prop_report.suma_S,
            "suma_Y": prop_report.suma_Y,
            "multiplicador_global": (
                prop_report.multiplicador_global
                if prop_report.multiplicador_global is not None else float("nan")
            ),
            "condicion_I_menos_rhoW": prop_report.condicion_I_menos_rhoW,
        })

    df_sensibilidad = pd.DataFrame(
        filas, columns=["rho", "suma_S", "suma_Y", "multiplicador_global", "condicion_I_menos_rhoW"],
    ).sort_values("rho").reset_index(drop=True)

    meta = {
        "radio_espectral_W": radio_espectral,
        "rho_max_efectivo": rho_max_efectivo,
        "criterio": sm.criterio,
        "n_agebs": len(sm.ids),
        "n_rho_evaluados": len(filas),
        "n_rho_invalidos": len(errores),
        "errores": errores,
        "allocation_report": alloc_report.to_dict(),
        "shock_vector_report": shock_report.to_dict(),
    }
    return df_sensibilidad, meta


__all__ = [
    "IMPACTO_DIRECTO_COL",
    "IMPACTO_PROPAGADO_COL",
    "IMPACTO_INDIRECTO_COL",
    "SimulationReport",
    "run_simulation_engine",
    "run_rho_sensitivity",
]