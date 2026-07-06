from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import geopandas as gpd
import pandas as pd

from spatial.allocation.allocator import (
    AllocationReport,
    generate_shock_ageb,
    normalize_shock_vector,
)
from spatial.config import AGEB_ID_COL, SSD_DIR, WAREHOUSE_PARQUET
from spatial.warehouse.builder import SECTOR_COL

SHOCK_AGEB_PARQUET = SSD_DIR / "shock_ageb.parquet"

DEFAULT_SECTOR_COL = "scian"
DEFAULT_DELTA_COL = "delta_X_pesos"


def shock_from_resultado_simulacion(
    resultado_simulacion: Mapping[str, Any],
    sector_col: str = DEFAULT_SECTOR_COL,
    delta_col: str = DEFAULT_DELTA_COL,
) -> pd.Series:
    if "df_detalle" not in resultado_simulacion:
        raise ValueError(
            "`resultado_simulacion` no tiene la clave 'df_detalle'. Se espera "
            "el dict devuelto por ModeloEconomico.simular() (serio/loader.py)."
        )

    df = resultado_simulacion["df_detalle"]
    if not isinstance(df, pd.DataFrame):
        raise ValueError(
            f"`resultado_simulacion['df_detalle']` debe ser un pd.DataFrame, "
            f"se recibió {type(df)}."
        )

    missing = {sector_col, delta_col} - set(df.columns)
    if missing:
        raise ValueError(
            f"`df_detalle` no tiene la(s) columna(s) {sorted(missing)}. "
            f"Se esperan ('{sector_col}', '{delta_col}') tal como las produce "
            "ModeloEconomico.simular()."
        )

    if df[sector_col].duplicated().any():
        dupes = sorted(df.loc[df[sector_col].duplicated(keep=False), sector_col].unique().tolist())
        raise ValueError(f"`df_detalle` tiene sectores duplicados en '{sector_col}': {dupes}.")

    sectores = df[sector_col].astype(str).tolist()
    delta_x = df[delta_col].astype(float).tolist()
    return normalize_shock_vector(sectores, delta_x)


def generate_shock_ageb_from_simulacion(
    resultado_simulacion: Mapping[str, Any],
    parquet_path: str | Path = WAREHOUSE_PARQUET,
    output_path: str | Path = SHOCK_AGEB_PARQUET,
    integrity_report: Optional[dict] = None,
    id_col: str = AGEB_ID_COL,
    sector_col: str = SECTOR_COL,
    shock_sector_col: str = DEFAULT_SECTOR_COL,
    shock_delta_col: str = DEFAULT_DELTA_COL,
    tol: float = 1e-6,
    write: bool = True,
) -> tuple[gpd.GeoDataFrame, AllocationReport]:
    shock_series = shock_from_resultado_simulacion(
        resultado_simulacion, sector_col=shock_sector_col, delta_col=shock_delta_col
    )
    return generate_shock_ageb(
        shock_series,
        parquet_path=parquet_path,
        output_path=output_path,
        integrity_report=integrity_report,
        id_col=id_col,
        sector_col=sector_col,
        tol=tol,
        write=write,
    )