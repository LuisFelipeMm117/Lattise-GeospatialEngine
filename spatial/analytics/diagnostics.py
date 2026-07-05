# spatial/analytics/diagnostics.py
"""
Diagnostics — Capa de QA (Especificación Formal v3.0, Sección 8, Stage 6).

Responsabilidad:
    Auditar `warehouse.parquet` + `metadata.json` (que ya embebe
    `join_report` e `integrity_report` producidos por
    `WarehouseBuilder.build()/build_from_gdfs()` en Stage 5) y producir
    `quality_report.json`: balances agregados de empleo/establecimientos
    asignados vs. huérfanos, cobertura sectorial, y consistencia cruzada
    entre los artefactos ya persistidos.

Este módulo es de solo lectura sobre resultados YA calculados:
    - NO vuelve a ejecutar el Spatial Join (Stage 4 / `spatial_join()`).
    - NO vuelve a aplicar ni resolver el Crosswalk SCIAN→SERIO.
    - NO recalcula ω_{g,s} (`compute_weights()`).
    - NO modifica `warehouse.parquet` ni `metadata.json`.
Únicamente agrega, cruza y etiqueta columnas/reportes que
`WarehouseBuilder` ya dejó calculados — mismo criterio de Layer
Isolation y Explicit Data Contracts (Sección 5) usado en los módulos
de Stage 1→5.

Fuente de `join_report` / `integrity_report`:
    `WarehouseBuilder.to_warehouse_files()` los embebe como dicts dentro
    de `metadata.json` (claves `"join_report"` / `"integrity_report"`).
    Si en algún flujo se serializaron aparte con
    `SpatialJoinReport.to_json()` / `WarehouseIntegrityReport.to_json()`,
    este módulo también puede leerlos desde esos archivos standalone
    (parámetros `join_report_path` / `integrity_report_path`) — nunca
    inventa un reporte si no encuentra ninguna de las dos fuentes.

Depende de (solo como consumidor de sus artefactos, no como caller):
    - spatial.warehouse.builder.WarehouseBuilder   (Stage 5 — LISTO)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import geopandas as gpd

from spatial.config import (
    AGEB_ID_COL,
    N_SECTORES_SERIO,
    QUALITY_REPORT_JSON,
    WAREHOUSE_METADATA,
    WAREHOUSE_PARQUET,
)
from spatial.warehouse.builder import SECTOR_COL

logger = logging.getLogger("sew.analytics.diagnostics")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

_OMEGA_METODOS = ("empleo", "establecimientos", "sin_datos")


# ══════════════════════════════════════════════════════════════════════════
# Reporte de calidad (Stage 6) — mismo patrón que los reportes de Stage 1→5
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class QualityReport:
    n_rows: int
    warehouse_summary: dict = field(default_factory=dict)
    join_consistency: dict = field(default_factory=dict)
    integrity_consistency: dict = field(default_factory=dict)
    omega_method_breakdown: dict = field(default_factory=dict)
    sector_distribution: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    overall_status: str = "OK"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Quality Report — {self.n_rows} pares (AGEB, sector_serio) auditados",
            f"  estatus general: {self.overall_status}",
            "  resumen del warehouse:",
        ]
        for k, v in self.warehouse_summary.items():
            lines.append(f"    - {k}: {v}")
        lines.append("  consistencia vs. join_report:")
        for k, v in self.join_consistency.items():
            lines.append(f"    - {k}: {v}")
        lines.append("  consistencia vs. integrity_report:")
        for k, v in self.integrity_consistency.items():
            lines.append(f"    - {k}: {v}")
        if self.flags:
            lines.append("  ⚠ flags:")
            for f_ in self.flags:
                lines.append(f"    - {f_}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Carga — solo lectura de artefactos ya producidos por Stage 5
# ══════════════════════════════════════════════════════════════════════════
def load_warehouse(parquet_path: str | Path = WAREHOUSE_PARQUET) -> gpd.GeoDataFrame:
    """Lee `warehouse.parquet` tal cual — sin recalcular ni reordenar nada."""
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró warehouse.parquet en '{path}'. Ejecuta "
            "WarehouseBuilder.build()/build_from_gdfs() + to_warehouse_files() (Stage 5) primero."
        )
    gdf = gpd.read_parquet(path)
    logger.info("Warehouse cargado: %s (%d filas).", path.name, len(gdf))
    return gdf


def load_metadata(metadata_path: str | Path = WAREHOUSE_METADATA) -> dict:
    """Lee `metadata.json` tal cual — incluye join_report/integrity_report embebidos."""
    path = Path(metadata_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró metadata.json en '{path}'. Ejecuta "
            "WarehouseBuilder.to_warehouse_files() (Stage 5) primero."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_standalone_report(path: Optional[str | Path]) -> Optional[dict]:
    """Lee un reporte serializado aparte (p.ej. `SpatialJoinReport.to_json()`)."""
    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el reporte standalone '{path}'.")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_reports(
    metadata: dict,
    join_report_path: Optional[str | Path] = None,
    integrity_report_path: Optional[str | Path] = None,
) -> tuple[dict, dict]:
    """
    Resuelve `join_report` / `integrity_report` — prioriza archivos
    standalone si se pasan explícitamente; si no, usa los dicts ya
    embebidos en `metadata.json` por `to_warehouse_files()`. Nunca
    inventa un reporte: si ninguna fuente los tiene, falla explícito
    (Explicit Data Contracts, Sección 5) en vez de auditar a ciegas.
    """
    join_report = _load_standalone_report(join_report_path) or metadata.get("join_report")
    integrity_report = _load_standalone_report(integrity_report_path) or metadata.get("integrity_report")

    if join_report is None:
        raise ValueError(
            "No hay join_report disponible (ni standalone ni embebido en metadata.json). "
            "No se puede auditar consistencia del Spatial Join sin él."
        )
    if integrity_report is None:
        raise ValueError(
            "No hay integrity_report disponible (ni standalone ni embebido en metadata.json). "
            "No se puede auditar consistencia de integridad sin él."
        )
    return join_report, integrity_report


# ══════════════════════════════════════════════════════════════════════════
# Cálculo de métricas de calidad — solo agregación sobre lo ya calculado
# ══════════════════════════════════════════════════════════════════════════
def compute_quality_report(
    gdf: gpd.GeoDataFrame,
    metadata: dict,
    join_report: dict,
    integrity_report: dict,
    sector_col: str = SECTOR_COL,
    id_col: str = AGEB_ID_COL,
    n_sectores_universo: Optional[int] = N_SECTORES_SERIO,
    top_n: int = 10,
) -> QualityReport:
    """
    Calcula el diagnóstico de calidad a partir de:
      - `gdf`: warehouse ya ensamblado (columnas de Stage 5, sin tocar).
      - `metadata`, `join_report`, `integrity_report`: reportes de
        Stage 4/5 ya serializados.

    NO recalcula ω, NO rehace el join, NO rehace el crosswalk — solo
    suma, agrupa y cruza columnas/campos que ya existen.
    """
    n = len(gdf)
    flags: list[str] = []

    # ── Resumen del warehouse (agregación pura sobre columnas existentes) ──
    n_agebs = int(gdf[id_col].nunique()) if id_col in gdf.columns and n else 0
    n_sectores_presentes = int(gdf[sector_col].nunique()) if sector_col in gdf.columns and n else 0
    total_establecimientos = int(gdf["n_establecimientos"].sum()) if "n_establecimientos" in gdf.columns else 0
    total_empleo = float(gdf["empleo_total"].sum()) if "empleo_total" in gdf.columns else 0.0
    total_empleo_faltante = int(gdf["n_empleo_faltante"].sum()) if "n_empleo_faltante" in gdf.columns else 0

    sector_coverage_pct = (
        n_sectores_presentes / n_sectores_universo if n_sectores_universo else None
    )

    warehouse_summary = {
        "n_agebs_distintos": n_agebs,
        "n_sectores_presentes": n_sectores_presentes,
        "n_sectores_universo": n_sectores_universo,
        "sector_coverage_pct": sector_coverage_pct,
        "total_establecimientos": total_establecimientos,
        "total_empleo": total_empleo,
        "total_empleo_faltante": total_empleo_faltante,
    }

    if sector_coverage_pct is not None and sector_coverage_pct < 1.0:
        faltantes = n_sectores_universo - n_sectores_presentes
        flags.append(
            f"Cobertura sectorial incompleta: {n_sectores_presentes}/{n_sectores_universo} "
            f"sectores SERIO presentes ({faltantes} sin ningún establecimiento asignado)."
        )

    # ── Consistencia vs. join_report (cruce, no recálculo del join) ────────
    n_total_denue = join_report.get("n_total", 0)
    n_matched = join_report.get("n_matched", 0)
    n_orphan = join_report.get("n_orphan", 0)
    n_ambiguous = join_report.get("n_ambiguous", 0)

    matched_pct = (n_matched / n_total_denue) if n_total_denue else None
    orphan_pct = (n_orphan / n_total_denue) if n_total_denue else None
    ambiguous_pct = (n_ambiguous / n_total_denue) if n_total_denue else None

    # Establecimientos que el join asignó a un AGEB pero que no llegaron al
    # warehouse (p.ej. por no tener sector_serio mapeado) — resta aritmética
    # entre dos totales ya calculados, no una re-ejecución del join.
    n_matched_excluidos = n_matched - total_establecimientos

    join_consistency = {
        "n_total_denue": n_total_denue,
        "n_matched": n_matched,
        "n_orphan": n_orphan,
        "n_ambiguous": n_ambiguous,
        "matched_pct": matched_pct,
        "orphan_pct": orphan_pct,
        "ambiguous_pct": ambiguous_pct,
        "establecimientos_en_warehouse": total_establecimientos,
        "n_matched_excluidos_del_warehouse": n_matched_excluidos,
        "consistente": n_matched_excluidos >= 0,
    }

    if n_matched_excluidos < 0:
        flags.append(
            "INCONSISTENCIA: el warehouse contiene más establecimientos "
            f"({total_establecimientos}) que los reportados como asignados "
            f"por el Spatial Join ({n_matched}). Revisa que warehouse.parquet "
            "y metadata.json provengan de la misma corrida de build()."
        )
    if n_matched_excluidos > 0:
        flags.append(
            f"{n_matched_excluidos} establecimientos fueron asignados a un AGEB "
            "por el Spatial Join pero no llegaron al warehouse (crosswalk incompleto)."
        )
    if orphan_pct is not None and orphan_pct > 0.10:
        flags.append(
            f"Proporción de huérfanos elevada: {orphan_pct:.1%} de los establecimientos "
            "DENUE evaluados quedaron fuera de todo AGEB conocido."
        )
    if n_ambiguous:
        flags.append(f"{n_ambiguous} establecimientos quedaron ambiguos (límite compartido entre AGEBs).")

    # ── Consistencia vs. integrity_report (auditoría post-compilación) ─────
    n_pairs_reportados = integrity_report.get("n_ageb_sector_pairs", 0)
    n_invalid = integrity_report.get("n_invalid", 0)
    row_count_matches = n_pairs_reportados == n

    integrity_consistency = {
        "n_ageb_sector_pairs_reportados": n_pairs_reportados,
        "n_ageb_sector_pairs_en_parquet": n,
        "row_count_consistente": row_count_matches,
        "n_valid": integrity_report.get("n_valid", 0),
        "n_invalid": n_invalid,
        "coverage_establecimientos": integrity_report.get("coverage_establecimientos"),
        "coverage_empleo": integrity_report.get("coverage_empleo"),
        "sectors_omega_not_summing_to_one": integrity_report.get("sectors_omega_not_summing_to_one", []),
    }

    if not row_count_matches:
        flags.append(
            f"INCONSISTENCIA: integrity_report reporta {n_pairs_reportados} pares "
            f"(AGEB, sector_serio) pero warehouse.parquet tiene {n} filas — "
            "posible corrupción o desalineación entre metadata.json y el parquet."
        )
    if n_invalid:
        flags.append(f"{n_invalid} filas del warehouse fallan al menos un check de integridad (Stage 5).")
    if integrity_report.get("sectors_omega_not_summing_to_one"):
        flags.append(
            f"{len(integrity_report['sectors_omega_not_summing_to_one'])} sectores "
            "tienen ω que no suma 1 (tolerancia 1e-6)."
        )

    # ── Desglose por método de ω (lectura de 'omega_metodo', sin recalcular) ─
    if "omega_metodo" in gdf.columns and n:
        counts = gdf["omega_metodo"].value_counts(dropna=False)
        omega_method_breakdown = {
            metodo: {
                "n_filas": int(counts.get(metodo, 0)),
                "pct": float(counts.get(metodo, 0) / n),
            }
            for metodo in _OMEGA_METODOS
        }
        n_sin_datos = omega_method_breakdown.get("sin_datos", {}).get("n_filas", 0)
        if n_sin_datos:
            flags.append(
                f"{n_sin_datos} pares (AGEB, sector_serio) quedan sin ω calculable "
                "(ni empleo ni establecimientos > 0 en el sector)."
            )
    else:
        omega_method_breakdown = {}

    # ── Distribución sectorial (agrupación sobre columnas existentes) ──────
    sector_distribution: dict = {}
    if sector_col in gdf.columns and n:
        by_sector = gdf.groupby(sector_col).agg(
            n_establecimientos=("n_establecimientos", "sum"),
            empleo_total=("empleo_total", "sum"),
        )

        top_empleo = by_sector["empleo_total"].sort_values(ascending=False).head(top_n)
        top_estab = by_sector["n_establecimientos"].sort_values(ascending=False).head(top_n)

        sector_distribution["top_sectores_por_empleo"] = {
            str(s): float(v) for s, v in top_empleo.items()
        }
        sector_distribution["top_sectores_por_establecimientos"] = {
            str(s): int(v) for s, v in top_estab.items()
        }

        if "omega_metodo" in gdf.columns:
            metodo_por_sector = gdf.groupby(sector_col)["omega_metodo"].apply(set)
            sectores_sin_empleo = sorted(
                str(s) for s, metodos in metodo_por_sector.items()
                if metodos <= {"establecimientos", "sin_datos"}
            )
            sector_distribution["sectores_sin_dato_de_empleo"] = sectores_sin_empleo

    n_invalid_total = integrity_consistency["n_invalid"]
    if n_invalid_total > 0 or not row_count_matches or n_matched_excluidos < 0:
        overall_status = "CRITICAL"
    elif flags:
        overall_status = "WARNING"
    else:
        overall_status = "OK"

    report = QualityReport(
        n_rows=n,
        warehouse_summary=warehouse_summary,
        join_consistency=join_consistency,
        integrity_consistency=integrity_consistency,
        omega_method_breakdown=omega_method_breakdown,
        sector_distribution=sector_distribution,
        flags=flags,
        overall_status=overall_status,
    )
    logger.info("\n%s", report.summary())
    return report


# ══════════════════════════════════════════════════════════════════════════
# Orquestación — lee artefactos de Stage 5, escribe quality_report.json
# ══════════════════════════════════════════════════════════════════════════
def generate_quality_report(
    parquet_path: str | Path = WAREHOUSE_PARQUET,
    metadata_path: str | Path = WAREHOUSE_METADATA,
    join_report_path: Optional[str | Path] = None,
    integrity_report_path: Optional[str | Path] = None,
    output_path: str | Path = QUALITY_REPORT_JSON,
    sector_col: str = SECTOR_COL,
    id_col: str = AGEB_ID_COL,
    n_sectores_universo: Optional[int] = N_SECTORES_SERIO,
    top_n: int = 10,
    write: bool = True,
) -> QualityReport:
    """
    Pipeline completo de Stage 6: carga `warehouse.parquet` + `metadata.json`
    (con `join_report`/`integrity_report` embebidos o standalone), calcula
    el diagnóstico de calidad y lo serializa a `quality_report.json`.

    No requiere ni invoca `WarehouseBuilder` — es un consumidor de sus
    artefactos ya persistidos (Stage 5, cerrado).
    """
    gdf = load_warehouse(parquet_path)
    metadata = load_metadata(metadata_path)
    join_report, integrity_report = resolve_reports(metadata, join_report_path, integrity_report_path)

    report = compute_quality_report(
        gdf, metadata, join_report, integrity_report,
        sector_col=sector_col, id_col=id_col,
        n_sectores_universo=n_sectores_universo, top_n=top_n,
    )

    if write:
        report.to_json(output_path)
        logger.info("Quality report serializado: %s", output_path)

    return report


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if len(args) == 0:
        report = generate_quality_report()
    elif len(args) == 2:
        report = generate_quality_report(parquet_path=args[0], metadata_path=args[1])
    else:
        print(
            "Uso: python -m spatial.analytics.diagnostics [<warehouse.parquet> <metadata.json>]\n"
            "Sin argumentos usa las rutas por defecto de spatial.config."
        )
        sys.exit(1)

    print(report.summary())
