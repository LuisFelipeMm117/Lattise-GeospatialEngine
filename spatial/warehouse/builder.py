# spatial/warehouse/builder.py
"""
WarehouseBuilder
================
Orquestador del Spatial Economic Warehouse (SEW) — Especificación Formal
v3.0, Sección 8, Stage 5.

Responsabilidad:
    Ensamblar la salida de los tres contratos ya aprobados —
    `AGEBLoader`, `DENUELoader` y `CrosswalkBuilder` — en la unidad de
    observación atómica del warehouse: W = {(g, s)}, donde g es un AGEB
    y s un sector SERIO. Para cada par (g, s) se agregan establecimientos
    y empleo (Spatial Join AGEB × DENUE vía `shapely.STRtree`), se
    calcula el peso de distribución ω_{g,s} y se valida la integridad
    del resultado antes de exponerlo como `GeoDataFrame`.

Este módulo NO modifica ni reimplementa `AGEBLoader`, `DENUELoader` ni
`CrosswalkBuilder` — únicamente los invoca y ensambla su salida,
respetando el mismo criterio de Layer Isolation y Explicit Data
Contracts (Sección 5) ya usado en esos tres módulos:
    - Ningún establecimiento se descarta silenciosamente del join:
      huérfanos (fuera de todo AGEB) y ambiguos (cae en el límite
      compartido entre >1 AGEB) se etiquetan y reportan explícitamente.
    - Ningún sector_serio se infiere: los códigos SCIAN sin mapeo en el
      crosswalk quedan fuera de la agregación y se reportan aparte.
    - ω_{g,s} se calcula preferentemente sobre empleo; si un sector no
      tiene NINGÚN dato de empleo, se usa conteo de establecimientos
      como respaldo — y el método usado queda registrado por fila
      (columna `omega_metodo`), nunca de forma silenciosa.

Depende de:
    - spatial.warehouse.ageb_loader.AGEBLoader       (LISTO)
    - spatial.warehouse.denue_loader.DENUELoader     (LISTO)
    - spatial.warehouse.crosswalk.CrosswalkBuilder   (LISTO — contrato;
      la tabla de mapeo scian→sector_serio debe llenarse aparte)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.strtree import STRtree

from spatial.config import (
    AGEB_ID_COL,
    EPSG_TARGET,
    WAREHOUSE_METADATA,
    WAREHOUSE_PARQUET,
)
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.crosswalk import CrosswalkBuilder
from spatial.warehouse.denue_loader import DENUELoader

logger = logging.getLogger("sew.warehouse.builder")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

SECTOR_COL = "sector_serio"
EMPLEO_COL = "empleo_estimado"

_JOIN_STATUS_MATCHED = "matched"
_JOIN_STATUS_ORPHAN = "orphan"
_JOIN_STATUS_AMBIGUOUS = "ambiguous"


# ══════════════════════════════════════════════════════════════════════════
# Reporte del Spatial Join (Stage 4) — sin resolución automática
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SpatialJoinReport:
    n_total: int
    n_matched: int = 0
    n_orphan: int = 0
    n_ambiguous: int = 0
    orphan_ids: list = field(default_factory=list)
    ambiguous_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Spatial Join Report — {self.n_total} establecimientos evaluados",
            f"  asignados a un único AGEB: {self.n_matched}",
            f"  huérfanos (fuera de todo AGEB conocido): {self.n_orphan}",
            f"  ambiguos (caen en >1 AGEB, p.ej. límite compartido): {self.n_ambiguous}",
        ]
        if self.orphan_ids:
            lines.append(f"  ids huérfanos (muestra): {self.orphan_ids[:10]}")
        if self.ambiguous_ids:
            lines.append(f"  ids ambiguos (muestra): {self.ambiguous_ids[:10]}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Reporte de integridad del Warehouse (Stage 5)
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class WarehouseIntegrityReport:
    n_ageb_sector_pairs: int
    checks: dict = field(default_factory=dict)
    n_valid: int = 0
    n_invalid: int = 0
    sectors_omega_not_summing_to_one: list = field(default_factory=list)
    coverage_establecimientos: float = 0.0
    coverage_empleo: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Warehouse Integrity Report — {self.n_ageb_sector_pairs} pares (AGEB, sector_serio)",
            f"  válidos: {self.n_valid}  inválidos: {self.n_invalid}",
            f"  cobertura establecimientos (asignados / evaluados en join): {self.coverage_establecimientos:.2%}",
            f"  cobertura empleo (con empleo_estimado conocido): {self.coverage_empleo:.2%}",
            "  detalle por check:",
        ]
        for name, n_fail in self.checks.items():
            lines.append(f"    - {name}: {n_fail} fallas")
        if self.sectors_omega_not_summing_to_one:
            lines.append(f"  ⚠ sectores cuyos ω no suman 1 (tolerancia 1e-6): {self.sectors_omega_not_summing_to_one}")
        return "\n".join(lines)


class WarehouseBuilder:
    """
    Uso típico (desde archivos raw, delegando la ingesta a los loaders):

        wb = WarehouseBuilder(serio_sectors=modelo.sectores)
        warehouse = wb.build(
            ageb_path="data/raw/agebs.gpkg",
            denue_path="data/raw/denue.csv",
            crosswalk_path="crosswalk_scian_serio.csv",
        )
        wb.join_report.summary()       # diagnóstico Stage 4
        wb.integrity_report.summary()  # diagnóstico Stage 5

    Uso típico (a partir de GeoDataFrames ya normalizados/mapeados —
    p.ej. en pruebas, o cuando el crosswalk ya se aplicó aparte):

        warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)
    """

    def __init__(
        self,
        serio_sectors: Optional[list[str]] = None,
        epsg_target: int = EPSG_TARGET,
        id_col: str = AGEB_ID_COL,
    ):
        self.epsg_target = epsg_target
        self.id_col = id_col

        self.ageb_loader = AGEBLoader(epsg_target=epsg_target, id_col=id_col)
        self.denue_loader = DENUELoader(epsg_target=epsg_target)
        self.crosswalk_builder = (
            CrosswalkBuilder(serio_sectors=serio_sectors) if serio_sectors else None
        )

        # Últimos reportes generados por build()/build_from_gdfs(), expuestos
        # para inspección posterior (p.ej. antes de serializar a disco).
        self.join_report: Optional[SpatialJoinReport] = None
        self.integrity_report: Optional[WarehouseIntegrityReport] = None

    # ────────────────────────────────────────────────────────────────────
    # Carga — delega íntegramente en los loaders aprobados (Stage 1→3)
    # ────────────────────────────────────────────────────────────────────
    def load_ageb(self, path: str | Path, drop_invalid: bool = False) -> gpd.GeoDataFrame:
        """Ejecuta AGEBLoader.run() y devuelve el GeoDataFrame normalizado."""
        result = self.ageb_loader.run(path, drop_invalid=drop_invalid, save_intermediate=False)
        return result["normalized"]

    def load_denue(self, path: str | Path, drop_invalid: bool = False) -> gpd.GeoDataFrame:
        """Ejecuta DENUELoader.run() y devuelve el GeoDataFrame normalizado."""
        result = self.denue_loader.run(path, drop_invalid=drop_invalid)
        return result["normalized"]

    def apply_crosswalk(
        self,
        denue_gdf: gpd.GeoDataFrame,
        crosswalk_path: str | Path,
        scian_col: str = "scian",
    ) -> tuple[gpd.GeoDataFrame, list, object]:
        """
        Carga y valida la tabla scian→sector_serio con CrosswalkBuilder y
        la aplica sobre el DENUE normalizado. No resuelve ambigüedades ni
        inventa mapeos — eso es responsabilidad exclusiva del contrato.
        """
        if self.crosswalk_builder is None:
            raise ValueError(
                "WarehouseBuilder no fue inicializado con `serio_sectors`; "
                "no se puede construir/validar el crosswalk. Pasa "
                "serio_sectors=modelo.sectores (ver loader.py::ModeloEconomico) "
                "al constructor de WarehouseBuilder."
            )
        cw_df = self.crosswalk_builder.load(crosswalk_path)
        validated, cw_report = self.crosswalk_builder.validate(cw_df)
        lookup = self.crosswalk_builder.build_lookup(validated)
        mapped, unmapped_codes = self.crosswalk_builder.apply(denue_gdf, lookup, scian_col=scian_col)
        if unmapped_codes:
            logger.warning(
                "%d códigos SCIAN del DENUE no tienen mapeo en el crosswalk: %s",
                len(unmapped_codes), unmapped_codes,
            )
        return mapped, unmapped_codes, cw_report

    # ────────────────────────────────────────────────────────────────────
    # Stage 4 — Spatial Join AGEB × DENUE vía shapely.STRtree
    # ────────────────────────────────────────────────────────────────────
    def spatial_join(
        self,
        ageb_gdf: gpd.GeoDataFrame,
        denue_gdf: gpd.GeoDataFrame,
    ) -> tuple[gpd.GeoDataFrame, SpatialJoinReport]:
        """
        Point-in-polygon AGEB × DENUE resuelto con `shapely.strtree.STRtree`
        (predicate='covered_by', incluye frontera). Cada establecimiento se
        asigna al ÚNICO AGEB que lo contiene. Ningún registro se descarta
        ni se resuelve automáticamente:
          - 0 coincidencias  → huérfano (fuera de todo AGEB conocido)
          - 1 coincidencia   → asignado (`_join_status = 'matched'`)
          - >1 coincidencias → ambiguo (p.ej. cae exactamente en un límite
            compartido entre dos AGEBs); se excluye de la agregación y se
            reporta explícitamente — nunca "se queda con el primero".
        """
        if ageb_gdf.crs is None or denue_gdf.crs is None:
            raise ValueError("AGEB y DENUE deben tener CRS definido antes del spatial join.")
        if ageb_gdf.crs.to_epsg() != denue_gdf.crs.to_epsg():
            raise ValueError(
                f"CRS incompatible en spatial join: AGEB={ageb_gdf.crs} vs DENUE={denue_gdf.crs}. "
                "Ambos deben normalizarse al mismo EPSG_TARGET (spatial.config) antes de unir."
            )
        if self.id_col not in ageb_gdf.columns:
            raise ValueError(f"AGEB no tiene la columna id '{self.id_col}'.")
        if ageb_gdf[self.id_col].duplicated().any():
            dupes = sorted(set(ageb_gdf.loc[ageb_gdf[self.id_col].duplicated(keep=False), self.id_col]))
            raise ValueError(
                f"AGEB tiene valores duplicados de '{self.id_col}' — resuélvelo antes del join "
                f"(afecta la unicidad de la clave del warehouse). Duplicados: {dupes[:10]}"
            )

        ageb_gdf = ageb_gdf.reset_index(drop=True)
        denue_gdf = denue_gdf.reset_index(drop=True)

        tree = STRtree(ageb_gdf.geometry.values)
        ageb_ids = ageb_gdf[self.id_col].astype(str).to_numpy()

        n = len(denue_gdf)
        est_id_col = "id" if "id" in denue_gdf.columns else None

        matched_ageb_id = np.full(n, None, dtype=object)
        join_status = np.full(n, _JOIN_STATUS_ORPHAN, dtype=object)
        orphan_ids: list = []
        ambiguous_ids: list = []

        def _est_id(i: int) -> str:
            return str(denue_gdf.iloc[i][est_id_col]) if est_id_col else str(i)

        for i, pt in enumerate(denue_gdf.geometry.values):
            if pt is None or pt.is_empty:
                orphan_ids.append(_est_id(i))
                continue
            hits = tree.query(pt, predicate="covered_by")
            if len(hits) == 1:
                matched_ageb_id[i] = ageb_ids[hits[0]]
                join_status[i] = _JOIN_STATUS_MATCHED
            elif len(hits) == 0:
                orphan_ids.append(_est_id(i))
            else:
                join_status[i] = _JOIN_STATUS_AMBIGUOUS
                ambiguous_ids.append(_est_id(i))

        joined = denue_gdf.copy()
        joined[self.id_col] = matched_ageb_id
        joined["_join_status"] = join_status

        report = SpatialJoinReport(
            n_total=n,
            n_matched=int((join_status == _JOIN_STATUS_MATCHED).sum()),
            n_orphan=int((join_status == _JOIN_STATUS_ORPHAN).sum()),
            n_ambiguous=int((join_status == _JOIN_STATUS_AMBIGUOUS).sum()),
            orphan_ids=orphan_ids,
            ambiguous_ids=ambiguous_ids,
        )
        logger.info("\n%s", report.summary())
        return joined, report

    # ────────────────────────────────────────────────────────────────────
    # Agregación por (AGEB, sector_serio) — unidad atómica W
    # ────────────────────────────────────────────────────────────────────
    def aggregate(
        self,
        joined_denue_gdf: gpd.GeoDataFrame,
        ageb_gdf: gpd.GeoDataFrame,
        sector_col: str = SECTOR_COL,
        employment_col: str = EMPLEO_COL,
    ) -> gpd.GeoDataFrame:
        """
        Agrega establecimientos y empleo por (AGEB, sector_serio). Solo se
        agregan registros con `_join_status == 'matched'` y sector_serio
        no nulo — huérfanos, ambiguos y códigos SCIAN sin mapeo ya quedaron
        excluidos y reportados explícitamente aguas arriba (nunca de forma
        silenciosa).

        Columnas de salida: id_col, sector_serio, n_establecimientos,
        empleo_total, n_empleo_faltante (registros del grupo sin
        empleo_estimado conocido — se suman como 0 en empleo_total pero se
        cuentan aparte para no ocultar el faltante), geometry (AGEB).
        """
        if "_join_status" not in joined_denue_gdf.columns:
            raise ValueError("Ejecuta spatial_join() antes de aggregate(); falta la columna '_join_status'.")
        if sector_col not in joined_denue_gdf.columns:
            raise ValueError(f"DENUE no tiene la columna '{sector_col}'; ejecuta apply_crosswalk() primero.")
        if ageb_gdf[self.id_col].duplicated().any():
            raise ValueError(f"AGEB tiene valores duplicados de '{self.id_col}'.")

        matched_mask = joined_denue_gdf["_join_status"] == _JOIN_STATUS_MATCHED
        usable = joined_denue_gdf[matched_mask & joined_denue_gdf[sector_col].notna()].copy()

        n_excluded_unmapped_sector = int((matched_mask & joined_denue_gdf[sector_col].isna()).sum())
        if n_excluded_unmapped_sector:
            logger.warning(
                "%d establecimientos asignados a un AGEB pero SIN sector_serio mapeado "
                "se excluyen de la agregación (requieren completar el crosswalk).",
                n_excluded_unmapped_sector,
            )

        columns = [self.id_col, sector_col, "n_establecimientos", "empleo_total", "n_empleo_faltante"]

        if usable.empty:
            agg = pd.DataFrame(columns=columns)
        else:
            emp = usable[employment_col] if employment_col in usable.columns else pd.Series(np.nan, index=usable.index)
            usable = usable.assign(_emp=emp.to_numpy())
            agg = (
                usable.groupby([self.id_col, sector_col], dropna=False)
                .agg(
                    n_establecimientos=("_emp", "size"),
                    empleo_total=("_emp", "sum"),
                    n_empleo_faltante=("_emp", lambda s: int(s.isna().sum())),
                )
                .reset_index()
            )

        out = ageb_gdf[[self.id_col, "geometry"]].merge(agg, on=self.id_col, how="right")
        out = gpd.GeoDataFrame(out, geometry="geometry", crs=ageb_gdf.crs)
        return out

    # ────────────────────────────────────────────────────────────────────
    # Cálculo de pesos ω_{g,s}
    # ────────────────────────────────────────────────────────────────────
    def compute_weights(
        self,
        aggregated_gdf: gpd.GeoDataFrame,
        sector_col: str = SECTOR_COL,
    ) -> gpd.GeoDataFrame:
        """
        Calcula ω_{g,s}: la participación del AGEB g dentro del sector s,
        usada por allocation/weights.py (Stage 7) para repartir un shock
        ΔX_s entre AGEBs.

        Restricción (Especificación v3.0, Sección 3): sum_g ω_{g,s} = 1
        para todo sector s. Se calcula preferentemente sobre empleo_total;
        si un sector no tiene NINGÚN dato de empleo (todos NaN/0 dentro
        del sector), se usa n_establecimientos como respaldo explícito.
        El método usado por fila queda registrado en `omega_metodo`
        ('empleo' | 'establecimientos' | 'sin_datos') — nunca silencioso.
        """
        gdf = aggregated_gdf.copy()
        if gdf.empty:
            gdf["omega"] = pd.Series(dtype=float)
            gdf["omega_metodo"] = pd.Series(dtype=object)
            return gdf

        sector_emp_total = gdf.groupby(sector_col)["empleo_total"].transform("sum")
        sector_est_total = gdf.groupby(sector_col)["n_establecimientos"].transform("sum")

        use_employment = sector_emp_total > 0
        use_fallback = (~use_employment) & (sector_est_total > 0)

        omega = pd.Series(np.nan, index=gdf.index, dtype=float)
        metodo = pd.Series("sin_datos", index=gdf.index, dtype=object)

        omega.loc[use_employment] = gdf.loc[use_employment, "empleo_total"] / sector_emp_total.loc[use_employment]
        metodo.loc[use_employment] = "empleo"

        omega.loc[use_fallback] = gdf.loc[use_fallback, "n_establecimientos"] / sector_est_total.loc[use_fallback]
        metodo.loc[use_fallback] = "establecimientos"

        gdf["omega"] = omega
        gdf["omega_metodo"] = metodo

        n_sin_datos = int((metodo == "sin_datos").sum())
        if n_sin_datos:
            logger.warning(
                "%d filas (AGEB, sector) quedan sin ω calculable (ni empleo ni "
                "establecimientos > 0 en el sector); omega queda en NaN explícito.",
                n_sin_datos,
            )

        return gdf

    # ────────────────────────────────────────────────────────────────────
    # Validación de integridad (sin descarte, solo etiquetado + reporte)
    # ────────────────────────────────────────────────────────────────────
    def validate_integrity(
        self,
        aggregated_gdf: gpd.GeoDataFrame,
        join_report: SpatialJoinReport,
        sector_col: str = SECTOR_COL,
    ) -> WarehouseIntegrityReport:
        """
        Checks:
          1. chk_no_duplicate_pairs — (AGEB, sector_serio) es clave única
          2. chk_omega_present      — ω fue calculado (no nulo) para la fila
          3. chk_omega_sums_to_one  — sum_g ω_{g,s} == 1 por sector (tol. 1e-6)
          4. chk_no_negative_counts — n_establecimientos > 0, empleo_total >= 0
          5. chk_geometry_present   — la fila conserva la geometría del AGEB
        No descarta filas — únicamente etiqueta y reporta, igual que
        AGEBLoader.validate() / DENUELoader.validate() / CrosswalkBuilder.validate().
        """
        gdf = aggregated_gdf
        n = len(gdf)

        if n == 0:
            report = WarehouseIntegrityReport(
                n_ageb_sector_pairs=0,
                checks={}, n_valid=0, n_invalid=0,
                coverage_establecimientos=0.0, coverage_empleo=0.0,
            )
            logger.warning("Warehouse vacío: no hay pares (AGEB, sector_serio) para validar.")
            return report

        dup_mask = gdf.duplicated(subset=[self.id_col, sector_col], keep=False)
        chk_no_duplicate_pairs = ~dup_mask

        chk_omega_present = gdf["omega"].notna() if "omega" in gdf.columns else pd.Series(False, index=gdf.index)

        if "omega" in gdf.columns:
            omega_by_sector = gdf.groupby(sector_col)["omega"].sum(min_count=1)
            bad_sectors = sorted(
                str(s) for s, total in omega_by_sector.items()
                if pd.notna(total) and abs(total - 1.0) > 1e-6
            )
        else:
            bad_sectors = []
        chk_omega_sums_to_one = ~gdf[sector_col].astype(str).isin(bad_sectors)

        chk_no_negative_counts = (gdf["n_establecimientos"] > 0) & (gdf["empleo_total"].fillna(0) >= 0)
        chk_geometry_present = gdf.geometry.notna()

        check_series = {
            "chk_no_duplicate_pairs": chk_no_duplicate_pairs,
            "chk_omega_present": chk_omega_present,
            "chk_omega_sums_to_one": chk_omega_sums_to_one,
            "chk_no_negative_counts": chk_no_negative_counts,
            "chk_geometry_present": chk_geometry_present,
        }
        all_checks = pd.DataFrame(check_series, index=gdf.index)
        all_valid = all_checks.all(axis=1)

        n_est_included = int(gdf["n_establecimientos"].sum())
        n_est_evaluated = join_report.n_total if join_report is not None else n_est_included
        coverage_establecimientos = (n_est_included / n_est_evaluated) if n_est_evaluated else 0.0

        n_missing_emp = int(gdf["n_empleo_faltante"].sum()) if "n_empleo_faltante" in gdf.columns else 0
        coverage_empleo = 1.0 - (n_missing_emp / n_est_included) if n_est_included else 0.0

        report = WarehouseIntegrityReport(
            n_ageb_sector_pairs=n,
            checks={name: int((~mask).sum()) for name, mask in check_series.items()},
            n_valid=int(all_valid.sum()),
            n_invalid=int((~all_valid).sum()),
            sectors_omega_not_summing_to_one=bad_sectors,
            coverage_establecimientos=coverage_establecimientos,
            coverage_empleo=coverage_empleo,
        )
        logger.info("\n%s", report.summary())
        return report

    # ────────────────────────────────────────────────────────────────────
    # Orquestación completa
    # ────────────────────────────────────────────────────────────────────
    def build_from_gdfs(
        self,
        ageb_gdf: gpd.GeoDataFrame,
        denue_gdf: gpd.GeoDataFrame,
        sector_col: str = SECTOR_COL,
    ) -> gpd.GeoDataFrame:
        """
        Ensambla el warehouse a partir de GeoDataFrames ya normalizados
        (AGEB vía AGEBLoader, DENUE vía DENUELoader + CrosswalkBuilder.apply()).
        Punto de entrada preferido para pruebas y para integraciones donde
        el crosswalk se resuelve por separado.
        """
        if sector_col not in denue_gdf.columns:
            raise ValueError(
                f"DENUE no tiene la columna '{sector_col}'. Aplica el crosswalk "
                "(CrosswalkBuilder.apply() o WarehouseBuilder.apply_crosswalk()) antes de construir el warehouse."
            )

        joined, join_report = self.spatial_join(ageb_gdf, denue_gdf)
        aggregated = self.aggregate(joined, ageb_gdf, sector_col=sector_col)
        weighted = self.compute_weights(aggregated, sector_col=sector_col)
        integrity_report = self.validate_integrity(weighted, join_report, sector_col=sector_col)

        self.join_report = join_report
        self.integrity_report = integrity_report

        return weighted

    def build(
        self,
        ageb_path: str | Path,
        denue_path: str | Path,
        crosswalk_path: str | Path,
        scian_col: str = "scian",
        drop_invalid_ageb: bool = False,
        drop_invalid_denue: bool = False,
    ) -> gpd.GeoDataFrame:
        """
        Pipeline completo desde archivos raw: AGEBLoader → DENUELoader →
        CrosswalkBuilder → Spatial Join → Agregación → ω → validación.
        Devuelve el `GeoDataFrame` del warehouse (una fila por (AGEB, sector_serio)).
        Reportes de diagnóstico quedan disponibles en `self.join_report` y
        `self.integrity_report` tras la ejecución.
        """
        ageb_gdf = self.load_ageb(ageb_path, drop_invalid=drop_invalid_ageb)
        denue_gdf = self.load_denue(denue_path, drop_invalid=drop_invalid_denue)
        denue_gdf, _unmapped_codes, _cw_report = self.apply_crosswalk(
            denue_gdf, crosswalk_path, scian_col=scian_col
        )
        return self.build_from_gdfs(ageb_gdf, denue_gdf)

    # ────────────────────────────────────────────────────────────────────
    # Export (Versioned Outputs, Sección 8) — warehouse.parquet + metadata.json
    # ────────────────────────────────────────────────────────────────────
    def to_warehouse_files(
        self,
        gdf: gpd.GeoDataFrame,
        parquet_path: str | Path = WAREHOUSE_PARQUET,
        metadata_path: str | Path = WAREHOUSE_METADATA,
        sector_col: str = SECTOR_COL,
    ) -> tuple[Path, Path]:
        """
        Serializa el warehouse ensamblado. Requiere haber corrido
        build()/build_from_gdfs() en esta misma instancia (usa los
        reportes guardados en self.join_report / self.integrity_report).
        """
        parquet_path = Path(parquet_path)
        metadata_path = Path(metadata_path)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        gdf.to_parquet(parquet_path)

        metadata = {
            "n_rows": int(len(gdf)),
            "epsg": self.epsg_target,
            "id_col": self.id_col,
            "sector_col": sector_col,
            "sectors": sorted(gdf[sector_col].dropna().astype(str).unique().tolist()) if sector_col in gdf.columns else [],
            "join_report": self.join_report.to_dict() if self.join_report else None,
            "integrity_report": self.integrity_report.to_dict() if self.integrity_report else None,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info("Warehouse serializado: %s / %s", parquet_path, metadata_path)
        return parquet_path, metadata_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 5:
        print(
            "Uso: python -m spatial.warehouse.builder <ageb_path> <denue_path> "
            "<crosswalk_path> <sector1,sector2,...>"
        )
        sys.exit(1)

    ageb_arg, denue_arg, crosswalk_arg, sectors_arg = sys.argv[1:5]
    wb = WarehouseBuilder(serio_sectors=sectors_arg.split(","))
    warehouse_gdf = wb.build(ageb_arg, denue_arg, crosswalk_arg)
    print(wb.join_report.summary())
    print(wb.integrity_report.summary())
    wb.to_warehouse_files(warehouse_gdf)