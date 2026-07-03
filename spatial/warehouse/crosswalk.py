# spatial/warehouse/crosswalk.py
"""
CrosswalkBuilder
================
Construye y valida el mapeo SCIAN (código de actividad de 6 dígitos del
DENUE) → sector SERIO (uno de los 78 sectores del modelo, ver
`ModeloEconomico.sectores` en loader.py).

Estado del insumo: LA TABLA DE CORRESPONDENCIA AÚN NO EXISTE. Este módulo
se entrega como CONTRATO DE DATOS (Sección 5 — Explicit Data Contracts):
define el esquema exacto, genera una plantilla vacía para llenar, y valida
estrictamente cualquier tabla que se cargue — pero no inventa mapeos.

Axioma metodológico aplicado (Sección 6 — Unicidad del Mapeo Sectorial):
    "El tratamiento de cualquier excepción sectorial de asignación múltiple
    debe quedar expresamente registrado en el código de transformación del
    Crosswalk."
Por eso: un código SCIAN con más de un sector_serio asociado NUNCA se
resuelve automáticamente (ni "se queda con el primero", ni se promedia).
Se marca como excepción, se excluye del lookup utilizable, y se reporta.

Esquema de la tabla (CSV):
    scian_codigo   : str, código de actividad DENUE (idealmente 6 dígitos)
    sector_serio   : str, código de sector — debe pertenecer al universo S
                     de los 78 sectores de SERIO
    notas          : str, opcional — justificación del mapeo, fuente, etc.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pandas as pd

logger = logging.getLogger("sew.warehouse.crosswalk")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

CROSSWALK_SCHEMA = ["scian_codigo", "sector_serio", "notas"]


@dataclass
class CrosswalkValidationReport:
    n_total: int
    checks: dict = field(default_factory=dict)
    n_valid: int = 0
    n_invalid: int = 0
    duplicated_codes: list = field(default_factory=list)   # excepción: 1 SCIAN → N sectores
    codes_outside_universe: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Crosswalk Validation Report — {self.n_total} filas evaluadas",
            f"  válidas:   {self.n_valid}",
            f"  inválidas: {self.n_invalid}",
            "  detalle por check:",
        ]
        for name, n_fail in self.checks.items():
            lines.append(f"    - {name}: {n_fail} fallas")
        if self.duplicated_codes:
            lines.append(f"  ⚠ códigos SCIAN con mapeo múltiple (requieren resolución manual): {self.duplicated_codes}")
        if self.codes_outside_universe:
            lines.append(f"  ⚠ sector_serio fuera del universo de 78 sectores: {self.codes_outside_universe}")
        return "\n".join(lines)


class CrosswalkBuilder:
    """
    Uso típico:
        cb = CrosswalkBuilder(serio_sectors=modelo.sectores)
        cb.generate_template("crosswalk_scian_serio.csv")   # una sola vez
        # ... se llena manualmente / con apoyo de un experto sectorial ...
        df = cb.load("crosswalk_scian_serio.csv")
        df, report = cb.validate(df)
        lookup = cb.build_lookup(df)                        # solo filas válidas y únicas
        denue_mapeado, unmapped = cb.apply(denue_gdf, lookup, scian_col="scian")
    """

    def __init__(self, serio_sectors: list[str]):
        if not serio_sectors:
            raise ValueError(
                "CrosswalkBuilder requiere el universo S de sectores SERIO "
                "(p.ej. modelo.sectores de loader.py::ModeloEconomico)."
            )
        self.serio_sectors = list(serio_sectors)

    # ────────────────────────────────────────────────────────────────────
    # Plantilla vacía — el contrato de datos en sí
    # ────────────────────────────────────────────────────────────────────
    def generate_template(self, path: str | Path) -> Path:
        """
        Genera un CSV vacío con el esquema correcto y, como referencia,
        un segundo archivo *_sectores_serio_referencia.csv con la lista
        completa de los 78 códigos válidos de sector_serio (para copiar/pegar
        al llenar la tabla manualmente).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        pd.DataFrame(columns=CROSSWALK_SCHEMA).to_csv(path, index=False)

        ref_path = path.with_name(path.stem + "_sectores_serio_referencia.csv")
        pd.DataFrame({"sector_serio": self.serio_sectors}).to_csv(ref_path, index=False)

        logger.info("Plantilla de crosswalk creada: %s", path)
        logger.info("Referencia de %d sectores SERIO válidos: %s", len(self.serio_sectors), ref_path)
        return path

    # ────────────────────────────────────────────────────────────────────
    # Ingesta
    # ────────────────────────────────────────────────────────────────────
    def load(self, path: str | Path) -> pd.DataFrame:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"No se encontró {path}. Genera primero la plantilla con "
                "generate_template() si aún no existe la tabla."
            )
        df = pd.read_csv(path, dtype=str)
        missing = set(CROSSWALK_SCHEMA) - set(df.columns)
        if missing:
            raise ValueError(f"El crosswalk no cumple el esquema esperado. Faltan columnas: {missing}")
        logger.info("Ingesta de crosswalk completa: %s (%d filas).", path.name, len(df))
        return df

    # ────────────────────────────────────────────────────────────────────
    # Validación — sin resolución automática de excepciones
    # ────────────────────────────────────────────────────────────────────
    def validate(self, df: pd.DataFrame) -> tuple[pd.DataFrame, CrosswalkValidationReport]:
        """
        Checks:
          1. chk_scian_not_null
          2. chk_scian_format     — 6 dígitos numéricos (INEGI estándar)
          3. chk_sector_not_null
          4. chk_sector_in_universe — sector_serio ∈ self.serio_sectors
          5. chk_scian_unique       — el código SCIAN no aparece más de una vez
        """
        df = df.copy()
        n = len(df)

        scian = df["scian_codigo"].astype(str).str.strip()
        sector = df["sector_serio"].astype(str).str.strip()

        df["chk_scian_not_null"]  = scian.ne("") & scian.ne("nan") & df["scian_codigo"].notna()
        df["chk_scian_format"]    = scian.str.fullmatch(r"\d{6}").fillna(False)
        df["chk_sector_not_null"] = sector.ne("") & sector.ne("nan") & df["sector_serio"].notna()
        df["chk_sector_in_universe"] = sector.isin(self.serio_sectors)

        dup_mask = scian.duplicated(keep=False) & df["chk_scian_not_null"]
        df["chk_scian_unique"] = ~dup_mask

        check_cols = [
            "chk_scian_not_null", "chk_scian_format", "chk_sector_not_null",
            "chk_sector_in_universe", "chk_scian_unique",
        ]
        df["_valid_mapping"] = df[check_cols].all(axis=1)

        report = CrosswalkValidationReport(
            n_total=n,
            checks={c: int((~df[c]).sum()) for c in check_cols},
            n_valid=int(df["_valid_mapping"].sum()),
            n_invalid=int((~df["_valid_mapping"]).sum()),
            duplicated_codes=sorted(set(scian[dup_mask])),
            codes_outside_universe=sorted(set(sector[~df["chk_sector_in_universe"] & df["chk_sector_not_null"]])),
        )
        logger.info("\n%s", report.summary())
        return df, report

    # ────────────────────────────────────────────────────────────────────
    # Lookup utilizable — SOLO filas válidas y sin ambigüedad
    # ────────────────────────────────────────────────────────────────────
    def build_lookup(self, validated_df: pd.DataFrame) -> dict[str, str]:
        if "_valid_mapping" not in validated_df.columns:
            raise ValueError("Ejecuta validate() antes de build_lookup().")
        valid = validated_df[validated_df["_valid_mapping"]]
        lookup = dict(zip(valid["scian_codigo"].astype(str).str.strip(),
                           valid["sector_serio"].astype(str).str.strip()))
        logger.info("Lookup construido con %d mapeos SCIAN→sector_serio válidos y no ambiguos.", len(lookup))
        return lookup

    # ────────────────────────────────────────────────────────────────────
    # Aplicación sobre el DENUE normalizado
    # ────────────────────────────────────────────────────────────────────
    def apply(self, denue_df: pd.DataFrame, lookup: dict[str, str], scian_col: str = "scian"):
        """
        Agrega la columna `sector_serio` al DENUE. Los códigos SCIAN
        presentes en el DENUE pero ausentes del lookup se dejan como NaN
        y se devuelven aparte en `unmapped_codes` — no se descartan filas
        ni se asigna un sector por default.
        """
        denue_df = denue_df.copy()
        scian_str = denue_df[scian_col].astype(str).str.strip()
        denue_df["sector_serio"] = scian_str.map(lookup)

        unmapped_mask = denue_df["sector_serio"].isna() & scian_str.ne("") & scian_str.ne("nan")
        unmapped_codes = sorted(set(scian_str[unmapped_mask]))
        if unmapped_codes:
            logger.warning(
                "%d códigos SCIAN del DENUE no tienen mapeo en el crosswalk (%d registros afectados). "
                "Requieren completarse manualmente en la tabla.",
                len(unmapped_codes), int(unmapped_mask.sum()),
            )
        return denue_df, unmapped_codes


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m spatial.warehouse.crosswalk <ruta_salida_template.csv> [sector1,sector2,...]")
        sys.exit(1)

    sectors_arg = sys.argv[2].split(",") if len(sys.argv) > 2 else [f"SEC{i:03d}" for i in range(1, 79)]
    cb = CrosswalkBuilder(serio_sectors=sectors_arg)
    cb.generate_template(sys.argv[1])