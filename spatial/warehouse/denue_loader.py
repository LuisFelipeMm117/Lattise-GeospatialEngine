# spatial/warehouse/denue_loader.py
"""
DENUELoader
===========
Implementa Stage 1 (ingesta), Stage 2 (Validación) y Stage 3 (Normalización)
del DENUE (INEGI), siguiendo exactamente el mismo patrón que AGEBLoader:
validación explícita sin descarte silencioso, normalización separada.

Parser genérico: el DENUE se descarga con nombres de columna que varían
ligeramente entre versiones/entregas de INEGI (mayúsculas, acentos,
"latitud" vs "lat", etc.). En vez de asumir un esquema fijo, este loader
resuelve cada campo lógico contra una lista de alias conocidos
(`DENUE_COLUMN_ALIASES`). Si tu archivo real usa un nombre distinto,
solo agrega el alias a la lista correspondiente — el resto del módulo
no cambia (mismo criterio de "Explicit Data Contracts", Sección 5).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from spatial.config import EPSG_TARGET

logger = logging.getLogger("sew.warehouse.denue_loader")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

# ══════════════════════════════════════════════════════════════════════════
# Contrato de columnas — alias conocidos por campo lógico
# ══════════════════════════════════════════════════════════════════════════
DENUE_COLUMN_ALIASES: dict[str, list[str]] = {
    "id":       ["id", "clee", "id_denue", "folio"],
    "nombre":   ["nom_estab", "nombre", "nombre_establecimiento"],
    "scian":    ["codigo_act", "scian", "clase_actividad", "cod_scian", "codigo_scian"],
    "lat":      ["latitud", "lat", "y"],
    "lon":      ["longitud", "lon", "lng", "x"],
    "per_ocu":  ["per_ocu", "personal_ocupado", "estrato_personal"],
}

# Bounding box aproximado de México continental + insular (grados decimales)
MX_LAT_RANGE = (14.0, 33.0)
MX_LON_RANGE = (-119.0, -86.0)

# Rangos oficiales DENUE de personal ocupado → punto medio estimado
PER_OCU_MIDPOINT: dict[str, float] = {
    "0 a 5 personas": 2.5,
    "6 a 10 personas": 8.0,
    "11 a 30 personas": 20.5,
    "31 a 50 personas": 40.5,
    "51 a 100 personas": 75.5,
    "101 a 250 personas": 175.5,
    "251 y más personas": 300.0,
}


def _resolve_columns(df: pd.DataFrame) -> dict[str, Optional[str]]:
    """Resuelve cada campo lógico contra el nombre de columna real presente."""
    cols_lower = {c.lower().strip(): c for c in df.columns}
    resolved: dict[str, Optional[str]] = {}
    for field_name, aliases in DENUE_COLUMN_ALIASES.items():
        found = next((cols_lower[a] for a in aliases if a in cols_lower), None)
        resolved[field_name] = found
        if found is None:
            logger.warning("Campo lógico '%s' no encontrado (alias probados: %s).", field_name, aliases)
    return resolved


# ══════════════════════════════════════════════════════════════════════════
# Reporte de validación — mismo patrón que AGEBValidationReport
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class DENUEValidationReport:
    n_total: int
    resolved_columns: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    n_valid: int = 0
    n_invalid: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"DENUE Validation Report — {self.n_total} registros evaluados",
            f"  columnas resueltas: {self.resolved_columns}",
            f"  válidos:   {self.n_valid}",
            f"  inválidos: {self.n_invalid}",
            "  detalle por check:",
        ]
        for name, n_fail in self.checks.items():
            lines.append(f"    - {name}: {n_fail} fallas")
        return "\n".join(lines)


class DENUELoader:
    """
    Orquesta Stage 1 → Stage 2 → Stage 3 para el DENUE. Salida lista para
    el Spatial Join de Stage 4 (join contra AGEBs vía STRtree) una vez
    que el CrosswalkBuilder resuelva scian → sector_serio.
    """

    def __init__(self, epsg_target: int = EPSG_TARGET):
        self.epsg_target = epsg_target

    # ────────────────────────────────────────────────────────────────────
    # Stage 1 — Ingesta
    # ────────────────────────────────────────────────────────────────────
    def load(self, path: str | Path) -> pd.DataFrame:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"No se encontró el archivo DENUE: {path}")

        # INEGI distribuye el DENUE en distintas codificaciones según la región/año
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(path, encoding=enc, low_memory=False)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"No se pudo decodificar {path} con utf-8/latin-1/cp1252.")

        logger.info("Ingesta DENUE completa: %s (%d registros).", path.name, len(df))
        return df

    # ────────────────────────────────────────────────────────────────────
    # Stage 2 — Validación (sin descarte)
    # ────────────────────────────────────────────────────────────────────
    def validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, DENUEValidationReport]:
        """
        Checks:
          1. chk_lat_not_null
          2. chk_lon_not_null
          3. chk_lat_in_range   — dentro del bbox aproximado de México
          4. chk_lon_in_range
          5. chk_scian_present  — código de actividad no nulo/no vacío
          6. chk_id_unique
        Ningún registro se elimina aquí — solo se etiqueta.
        """
        df = df.copy()
        resolved = _resolve_columns(df)
        n = len(df)

        lat_col, lon_col, scian_col, id_col = (
            resolved["lat"], resolved["lon"], resolved["scian"], resolved["id"]
        )

        lat_num = pd.to_numeric(df[lat_col], errors="coerce") if lat_col else pd.Series([None] * n)
        lon_num = pd.to_numeric(df[lon_col], errors="coerce") if lon_col else pd.Series([None] * n)

        df["chk_lat_not_null"] = lat_num.notna()
        df["chk_lon_not_null"] = lon_num.notna()
        df["chk_lat_in_range"] = lat_num.between(*MX_LAT_RANGE)
        df["chk_lon_in_range"] = lon_num.between(*MX_LON_RANGE)

        if scian_col:
            scian_str = df[scian_col].astype(str).str.strip()
            df["chk_scian_present"] = scian_str.ne("") & scian_str.ne("nan") & df[scian_col].notna()
        else:
            df["chk_scian_present"] = False

        if id_col:
            df["chk_id_unique"] = ~df[id_col].duplicated(keep=False)
        else:
            logger.warning("Campo 'id' no resuelto — chk_id_unique se marca como fallido para todas las filas.")
            df["chk_id_unique"] = False

        check_cols = [
            "chk_lat_not_null", "chk_lon_not_null", "chk_lat_in_range",
            "chk_lon_in_range", "chk_scian_present", "chk_id_unique",
        ]
        df["_valid_record"] = df[check_cols].all(axis=1)

        report = DENUEValidationReport(
            n_total=n,
            resolved_columns=resolved,
            checks={c: int((~df[c]).sum()) for c in check_cols},
            n_valid=int(df["_valid_record"].sum()),
            n_invalid=int((~df["_valid_record"]).sum()),
        )
        logger.info("\n%s", report.summary())
        return df, report

    def filter_valid(self, df: pd.DataFrame) -> pd.DataFrame:
        if "_valid_record" not in df.columns:
            raise ValueError("Ejecuta validate() antes de filter_valid(); no hay descarte implícito.")
        n_before = len(df)
        out = df[df["_valid_record"]].copy()
        logger.info("filter_valid(): %d → %d registros (%d descartados explícitamente)",
                    n_before, len(out), n_before - len(out))
        return out

    # ────────────────────────────────────────────────────────────────────
    # Stage 3 — Normalización
    # ────────────────────────────────────────────────────────────────────
    def normalize(self, df: pd.DataFrame) -> gpd.GeoDataFrame:
        """
        - Renombra columnas resueltas a nombres estándar: id, nombre, scian, lat, lon, per_ocu.
        - Convierte per_ocu (rango textual DENUE) a `empleo_estimado` (punto medio).
          Rangos no reconocidos se dejan en NaN y se reportan (no se inventan).
        - Construye geometría de puntos, CRS 4326 → reproyectado a EPSG objetivo.
        """
        df = df.copy()
        resolved = _resolve_columns(df)

        rename_map = {v: k for k, v in resolved.items() if v is not None}
        df = df.rename(columns=rename_map)

        for req in ("lat", "lon"):
            if req not in df.columns:
                raise ValueError(f"No se puede normalizar sin columna '{req}' resuelta.")
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")

        if "per_ocu" in df.columns:
            df["empleo_estimado"] = df["per_ocu"].map(PER_OCU_MIDPOINT)
            n_unmapped = int(df["per_ocu"].notna().sum() - df["empleo_estimado"].notna().sum())
            if n_unmapped > 0:
                unmapped_vals = sorted(set(df.loc[df["empleo_estimado"].isna() & df["per_ocu"].notna(), "per_ocu"]))
                logger.warning(
                    "%d registros con rango de personal ocupado no reconocido: %s. "
                    "empleo_estimado queda en NaN para esos casos (no se infiere silenciosamente).",
                    n_unmapped, unmapped_vals,
                )
        else:
            df["empleo_estimado"] = float("nan")
            logger.warning("Campo 'per_ocu' no resuelto — empleo_estimado será NaN para todos los registros.")

        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326"
        )
        gdf = gdf.to_crs(epsg=self.epsg_target)

        logger.info("Normalización DENUE completa: CRS=EPSG:%d, %d registros.", self.epsg_target, len(gdf))
        return gdf

    # ────────────────────────────────────────────────────────────────────
    # Pipeline completo
    # ────────────────────────────────────────────────────────────────────
    def run(self, path: str | Path, drop_invalid: bool = False) -> dict:
        raw = self.load(path)
        validated, report = self.validate(raw)
        working = self.filter_valid(validated) if drop_invalid else validated
        normalized = self.normalize(working)
        return {"raw": raw, "validated": validated, "report": report, "normalized": normalized}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m spatial.warehouse.denue_loader <ruta_denue.csv>")
        sys.exit(1)

    loader = DENUELoader()
    result = loader.run(sys.argv[1])
    print(result["report"].summary())