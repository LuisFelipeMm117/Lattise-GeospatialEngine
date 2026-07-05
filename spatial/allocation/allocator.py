# spatial/allocation/allocator.py
"""
Allocator — Spatial Shock Distributor / SSD (Especificación Formal v3.0,
Sección 8, Stage 7).

Responsabilidad:
    Distribuir un vector de shocks sectoriales ΔX_s (proveniente de
    cualquier modelo de insumo-producto — SERIO u otro; este módulo no
    depende conceptualmente de ninguno) entre los AGEBs de cada sector,
    usando exclusivamente ω_{g,s} ya calculado por
    `WarehouseBuilder.compute_weights()` (Stage 5) y expuesto vía
    `allocation.weights.OmegaTable` (Stage 7, capa de acceso):

        shock_ageb_{g,s} = ω_{g,s} · ΔX_s

Este módulo NO recalcula nada aguas arriba — mismo criterio de Layer
Isolation y Explicit Data Contracts (Sección 5) usado en Stage 1→6:
    - NO vuelve a ejecutar el Spatial Join ni el Crosswalk.
    - NO recalcula ω_{g,s} — solo lee lo que `OmegaTable` ya organiza.
    - Sectores del shock sin ningún AGEB con ω conocido en el warehouse
      se EXCLUYEN del reparto y se reportan explícitamente
      (`sectores_sin_cobertura_espacial`) — nunca se infiere un reparto
      uniforme ni se descarta en silencio.
    - AGEBs con `omega_metodo == 'sin_datos'` ya quedaron fuera de
      `OmegaTable.omega_for()`; aquí solo se cuenta cuántos fueron
      (`n_agebs_excluidos_por_sector`), nunca se oculta el faltante.
    - Si se aporta `integrity_report` (Stage 5, ya serializado), se cruza
      contra `sectors_omega_not_summing_to_one` en vez de recalcular la
      suma de ω — mismo patrón que `analytics.diagnostics` reutilizando
      `join_report`/`integrity_report`.

Depende de (solo como consumidor de sus artefactos, no como caller):
    - spatial.allocation.weights.OmegaTable / load_omega_table   (Stage 7 — LISTO)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import geopandas as gpd
import pandas as pd

from spatial.allocation.weights import OmegaTable, load_omega_table
from spatial.config import AGEB_ID_COL, SSD_DIR, WAREHOUSE_PARQUET
from spatial.warehouse.builder import SECTOR_COL

logger = logging.getLogger("sew.allocation.allocator")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

SHOCK_AGEB_PARQUET = SSD_DIR / "shock_ageb.parquet"

ShockLike = Union[Mapping[Any, float], pd.Series, pd.DataFrame]


# ══════════════════════════════════════════════════════════════════════════
# Reporte del reparto (Stage 7) — mismo patrón que Stage 1→6
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class AllocationReport:
    n_sectores_shock: int
    n_sectores_distribuidos: int = 0
    sectores_sin_cobertura_espacial: list = field(default_factory=list)
    n_agebs_excluidos_por_sector: dict = field(default_factory=dict)
    omega_sum_by_sector: dict = field(default_factory=dict)
    sectores_omega_no_normalizado: list = field(default_factory=list)
    total_shock_distribuido: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Allocation Report (SSD) — {self.n_sectores_shock} sectores en el shock, "
            f"{self.n_sectores_distribuidos} distribuidos espacialmente",
        ]
        if self.sectores_sin_cobertura_espacial:
            lines.append(
                f"  ⚠ sin cobertura espacial en el warehouse (excluidos del reparto): "
                f"{self.sectores_sin_cobertura_espacial}"
            )
        for sector, n in self.n_agebs_excluidos_por_sector.items():
            if n:
                lines.append(f"  sector {sector}: {n} AGEB(s) excluidos (omega_metodo='sin_datos')")
        if self.sectores_omega_no_normalizado:
            lines.append(
                f"  ⚠ ω no suma 1 (tolerancia) en los sectores: {self.sectores_omega_no_normalizado}"
            )
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Normalización del vector de shock — agnóstica a cualquier modelo IO
# ══════════════════════════════════════════════════════════════════════════
def normalize_shock_vector(sectores: Sequence, delta_x: Sequence[float]) -> pd.Series:
    """
    Convierte un par posicional (códigos de sector, valores ΔX_s) — el
    formato típico de salida de cualquier modelo de insumo-producto
    (`L @ ΔY`, sea SERIO u otro) — al formato `{sector: ΔX_s}` que espera
    `allocate_shock()`. No importa ni depende de ningún modelo concreto:
    solo recibe las dos secuencias ya extraídas por el caller.
    """
    if len(sectores) != len(delta_x):
        raise ValueError(
            f"`sectores` (len={len(sectores)}) y `delta_x` (len={len(delta_x)}) "
            "deben tener la misma longitud."
        )
    return pd.Series(data=list(delta_x), index=list(sectores), dtype=float)


def _coerce_shock(shock: ShockLike, sector_col: str) -> pd.Series:
    """
    Normaliza cualquier representación aceptada de un shock sectorial —
    `dict`/`Mapping`, `pd.Series`, o `pd.DataFrame` con columnas
    (`sector_col`, `delta_x`) — a una `pd.Series` indexada por sector.
    """
    if isinstance(shock, pd.DataFrame):
        required = {sector_col, "delta_x"}
        missing = required - set(shock.columns)
        if missing:
            raise ValueError(
                f"DataFrame de shock sin la(s) columna(s) requerida(s) {sorted(missing)}. "
                f"Se esperan columnas ('{sector_col}', 'delta_x')."
            )
        if shock[sector_col].duplicated().any():
            dupes = sorted(shock.loc[shock[sector_col].duplicated(keep=False), sector_col].unique().tolist())
            raise ValueError(f"DataFrame de shock tiene sectores duplicados: {dupes}.")
        return shock.set_index(sector_col)["delta_x"].astype(float)

    if isinstance(shock, pd.Series):
        return shock.astype(float)

    if isinstance(shock, Mapping):
        return pd.Series(shock, dtype=float)

    raise TypeError(
        f"Tipo de shock no soportado: {type(shock)}. Usa dict/Mapping, pd.Series, "
        f"o pd.DataFrame con columnas ('{sector_col}', 'delta_x')."
    )


# ══════════════════════════════════════════════════════════════════════════
# Reparto — shock_ageb_{g,s} = ω_{g,s} · ΔX_s
# ══════════════════════════════════════════════════════════════════════════
def allocate_shock(
    shock: ShockLike,
    omega_table: OmegaTable,
    integrity_report: Optional[dict] = None,
    tol: float = 1e-6,
) -> tuple[gpd.GeoDataFrame, AllocationReport]:
    """
    Distribuye `shock` (uno o varios sectores) entre los AGEBs de
    `omega_table` usando ω ya calculado. Devuelve un `GeoDataFrame` con
    una fila por (AGEB, sector) repartido — geometría incluida, tomada de
    `omega_table.geometry` sin recalcular — y el `AllocationReport`
    correspondiente.

    Si `integrity_report` (Stage 5) se aporta, la columna
    `sectores_omega_no_normalizado` del reporte se resuelve leyendo
    `sectors_omega_not_summing_to_one` en vez de recalcular la suma de ω;
    si no se aporta, se calcula como un chequeo de lectura simple
    (sum(ω) ya vive en la columna, no se recalcula ω en sí).
    """
    sector_col = omega_table.sector_col
    id_col = omega_table.id_col
    shock_series = _coerce_shock(shock, sector_col=sector_col)

    known_bad = None
    if integrity_report is not None:
        known_bad = {str(s) for s in integrity_report.get("sectors_omega_not_summing_to_one", [])}

    rows: list[pd.DataFrame] = []
    sectores_sin_cobertura: list = []
    n_excluidos_por_sector: dict = {}
    omega_sum_by_sector: dict = {}
    sectores_no_normalizado: list = []
    total_distribuido: dict = {}

    for sector, delta_x in shock_series.items():
        if not omega_table.has_sector(sector):
            sectores_sin_cobertura.append(sector)
            continue

        sub = omega_table.rows_for(sector).copy()
        n_excluidos_por_sector[sector] = omega_table.n_agebs_sin_omega(sector)

        omega_sum = float(sub["omega"].sum())
        omega_sum_by_sector[sector] = omega_sum

        is_bad = (str(sector) in known_bad) if known_bad is not None else (abs(omega_sum - 1.0) > tol)
        if is_bad:
            sectores_no_normalizado.append(sector)

        sub["shock_sectorial"] = float(delta_x)
        sub["shock_ageb"] = sub["omega"] * float(delta_x)
        total_distribuido[sector] = float(sub["shock_ageb"].sum())

        rows.append(sub[[id_col, sector_col, "omega", "omega_metodo", "shock_sectorial", "shock_ageb"]])

    out_columns = [id_col, sector_col, "omega", "omega_metodo", "shock_sectorial", "shock_ageb"]
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=out_columns)

    geom_df = omega_table.geometry.reset_index()
    geom_df.columns = [id_col, "geometry"]
    out = out.merge(geom_df, on=id_col, how="left")
    out_gdf = gpd.GeoDataFrame(out, geometry="geometry", crs=omega_table.crs)

    report = AllocationReport(
        n_sectores_shock=len(shock_series),
        n_sectores_distribuidos=len(shock_series) - len(sectores_sin_cobertura),
        sectores_sin_cobertura_espacial=sectores_sin_cobertura,
        n_agebs_excluidos_por_sector=n_excluidos_por_sector,
        omega_sum_by_sector=omega_sum_by_sector,
        sectores_omega_no_normalizado=sectores_no_normalizado,
        total_shock_distribuido=total_distribuido,
    )
    logger.info("\n%s", report.summary())
    return out_gdf, report


# ══════════════════════════════════════════════════════════════════════════
# Orquestación — lee warehouse.parquet (Stage 5), escribe shock_ageb.parquet
# ══════════════════════════════════════════════════════════════════════════
def generate_shock_ageb(
    shock: ShockLike,
    parquet_path: str | Path = WAREHOUSE_PARQUET,
    output_path: str | Path = SHOCK_AGEB_PARQUET,
    integrity_report: Optional[dict] = None,
    id_col: str = AGEB_ID_COL,
    sector_col: str = SECTOR_COL,
    tol: float = 1e-6,
    write: bool = True,
) -> tuple[gpd.GeoDataFrame, AllocationReport]:
    """
    Pipeline completo de Stage 7: carga `warehouse.parquet` vía
    `allocation.weights.load_omega_table()`, distribuye `shock` con
    `allocate_shock()`, y serializa `shock_ageb.parquet` (con geometría,
    para evitar joins posteriores en Stage 8/9).

    No requiere ni invoca `WarehouseBuilder` — es un consumidor de su
    artefacto ya persistido (Stage 5, cerrado).
    """
    omega_table = load_omega_table(parquet_path, id_col=id_col, sector_col=sector_col)
    gdf, report = allocate_shock(shock, omega_table, integrity_report=integrity_report, tol=tol)

    if write:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(output_path)
        logger.info("shock_ageb.parquet serializado: %s", output_path)

    return gdf, report


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "Uso: python -m spatial.allocation.allocator '<shock_json>' [<warehouse.parquet>]\n"
            "  shock_json: mapeo JSON {sector_serio: delta_x}, p.ej. '{\"112\": 1000000}'\n"
            "Sin <warehouse.parquet> usa la ruta por defecto de spatial.config."
        )
        sys.exit(1)

    shock_arg = json.loads(sys.argv[1])
    if len(sys.argv) >= 3:
        result_gdf, result_report = generate_shock_ageb(shock_arg, parquet_path=sys.argv[2])
    else:
        result_gdf, result_report = generate_shock_ageb(shock_arg)

    print(result_report.summary())
