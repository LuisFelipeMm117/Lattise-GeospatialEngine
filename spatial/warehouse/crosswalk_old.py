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

────────────────────────────────────────────────────────────────────────────
CAPA DE AUTORÍA JERÁRQUICA (v2 — activo de datos SCIAN → SERIO)
────────────────────────────────────────────────────────────────────────────
Arquitectura aprobada:

    Autoría jerárquica → Validación → Compilación → Lookup plano → WarehouseBuilder

El bloque anterior de este módulo (CROSSWALK_SCHEMA, generate_template,
load, validate, build_lookup, apply, CrosswalkValidationReport) es EL
CONTRATO PÚBLICO EXISTENTE y no se modifica en absoluto: sigue siendo el
único punto de entrada que consume `WarehouseBuilder`.

Todo lo que sigue debajo es aditivo y vive encapsulado en esta misma clase
(`CrosswalkBuilder`), como una capa de autoría más rica que, al final,
se COMPILA hacia exactamente `CROSSWALK_SCHEMA` — nunca sale de aquí un
formato distinto al que el resto del pipeline ya sabe consumir.

Dos artefactos distintos:
    A) Crosswalk de autoría (AUTHORING_SCHEMA) — editable por humanos,
       admite reglas a nivel Sector/Subsector/Rama/Subrama/Clase.
    B) Crosswalk compilado (CROSSWALK_SCHEMA) — generado automáticamente
       por `compile_to_flat_lookup()`, contiene EXCLUSIVAMENTE pares
       SCIAN (6 dígitos) → sector SERIO. Es el único artefacto que
       `WarehouseBuilder` conoce.

Regla dura (no negociable): ninguna inferencia jerárquica genera
`status=VERIFIED` por sí sola. Toda fila heredada nace como
`evidence_type=INFERRED, status=PENDING` y solo una revisión humana
explícita puede convertirla en `VERIFIED`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
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


# ════════════════════════════════════════════════════════════════════════
# ETAPA 0 — JERARQUÍA SCIAN (utilidades puras, sin dependencias externas)
# ════════════════════════════════════════════════════════════════════════
class SCIANLevel(str, Enum):
    """Los 5 niveles oficiales de la taxonomía SCIAN, de más general a
    más específico. El valor numérico asociado en `SCIAN_LEVEL_DIGITS`
    es la longitud de dígitos que le corresponde a cada nivel."""
    SECTOR = "SECTOR"
    SUBSECTOR = "SUBSECTOR"
    RAMA = "RAMA"
    SUBRAMA = "SUBRAMA"
    CLASE = "CLASE"


SCIAN_LEVEL_DIGITS: dict[SCIANLevel, int] = {
    SCIANLevel.SECTOR: 2,
    SCIANLevel.SUBSECTOR: 3,
    SCIANLevel.RAMA: 4,
    SCIANLevel.SUBRAMA: 5,
    SCIANLevel.CLASE: 6,
}

# Orden de resolución jerárquica: del nivel MÁS ESPECÍFICO al MÁS GENERAL.
# Este es el orden de precedencia oficial acordado para el proyecto:
#     Clase → Subrama → Rama → Subsector → Sector
RESOLUTION_ORDER: tuple[SCIANLevel, ...] = (
    SCIANLevel.CLASE, SCIANLevel.SUBRAMA, SCIANLevel.RAMA,
    SCIANLevel.SUBSECTOR, SCIANLevel.SECTOR,
)


def scian_ancestors(code6: str) -> dict[SCIANLevel, str]:
    """
    Dado un código de Clase (6 dígitos), devuelve el prefijo que le
    corresponde a cada nivel ancestro de la jerarquía SCIAN.

    Ejemplo: scian_ancestors("311611") ==
        {CLASE: "311611", SUBRAMA: "31161", RAMA: "3116",
         SUBSECTOR: "311", SECTOR: "31"}
    """
    code6 = str(code6).strip()
    if not re.fullmatch(r"\d{6}", code6):
        raise ValueError(f"scian_ancestors() requiere un código de Clase de 6 dígitos numéricos; recibido: {code6!r}")
    return {level: code6[:digits] for level, digits in SCIAN_LEVEL_DIGITS.items()}


class EvidenceType(str, Enum):
    """Naturaleza de la evidencia detrás de una asignación de autoría.
    Dimensión INDEPENDIENTE de `AuthoringStatus` — nunca se mezclan."""
    OFFICIAL = "OFFICIAL"
    EXPERT = "EXPERT"
    INFERRED = "INFERRED"


class AuthoringStatus(str, Enum):
    """Estado del flujo de trabajo de una fila de autoría. Máquina de
    estados: PENDING → {VERIFIED | REVIEW_REQUIRED | OUT_OF_SCOPE}."""
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class MappingType(str, Enum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# Esquema del crosswalk de AUTORÍA (rico, jerárquico, editable por humanos).
# Distinto e independiente de CROSSWALK_SCHEMA (el artefacto compilado).
AUTHORING_SCHEMA: list[str] = [
    "scian_codigo", "scian_nivel", "scian_titulo",
    "serio_sector", "serio_nombre",
    "evidence_type", "status", "priority", "mapping_type",
    "source", "justification", "reviewed_by", "review_date", "notes",
    "crosswalk_version", "scian_version", "serio_version",
    "generated_at", "generated_by",
]


# ── Excepciones tipadas de validación de autoría (Fase 5) ──────────────────
class CrosswalkAuthoringError(Exception):
    """Excepción base para toda violación del contrato de datos de
    autoría jerárquica del crosswalk SCIAN → SERIO."""


class DuplicateSCIANError(CrosswalkAuthoringError):
    """Un `scian_codigo` aparece más de una vez en la tabla de autoría."""


class UnknownSERIOSectorError(CrosswalkAuthoringError):
    """Un `serio_sector` no pertenece al universo de sectores SERIO."""


class InvalidSCIANLengthError(CrosswalkAuthoringError):
    """La longitud de `scian_codigo` no coincide con la esperada para su
    `scian_nivel`, o `scian_nivel` no es uno de los 5 valores válidos."""


class NonNumericSCIANError(CrosswalkAuthoringError):
    """`scian_codigo` contiene caracteres no numéricos."""


class StateConsistencyError(CrosswalkAuthoringError):
    """Una fila no cumple el invariante de columnas exigido por su
    `status` (ver tabla de invariantes en `validate_authoring`)."""


# ── Resultado de la resolución jerárquica de un código ─────────────────────
@dataclass
class ScianResolution:
    """Resultado de `CrosswalkBuilder.resolve_scian_code()`. Cuando
    `resolved=True`, `matched_level` y `matched_scian_codigo` dan
    trazabilidad exacta de qué regla (y a qué nivel de la jerarquía)
    determinó el sector SERIO resultante."""
    scian_codigo: str
    resolved: bool
    serio_sector: str | None = None
    matched_level: SCIANLevel | None = None
    matched_scian_codigo: str | None = None


# ── Reporte de validación de autoría (Fase 5) ───────────────────────────────
@dataclass
class AuthoringValidationReport:
    n_total: int
    violations: dict = field(default_factory=dict)
    multiple_semantic_assignments: list = field(default_factory=list)
    n_valid: int = 0
    n_invalid: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Authoring Validation Report — {self.n_total} filas evaluadas",
            f"  válidas:   {self.n_valid}",
            f"  inválidas: {self.n_invalid}",
        ]
        for name, items in self.violations.items():
            if items:
                lines.append(f"  ⚠ {name}: {len(items)} caso(s) → {items}")
        if self.multiple_semantic_assignments:
            lines.append(
                f"  ⚠ scian_titulo con asignación a más de un sector SERIO "
                f"(requiere revisión, no se resuelve automáticamente): "
                f"{self.multiple_semantic_assignments}"
            )
        return "\n".join(lines)


# ── Reporte de cobertura del activo de datos (Fases 6–7) ────────────────────
@dataclass
class CrosswalkCoverageReport:
    metadata: dict
    totals: dict
    coverage: dict
    priority_breakdown: dict
    by_serio_sector: list
    review_queue: list
    unmapped_scian_codes: list
    validation_errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )

    def summary(self) -> str:
        c = self.coverage
        lines = [
            "Crosswalk Coverage Report",
            f"  coverage_catalog_pct: {c['coverage_catalog_pct']}%",
            f"  coverage_denue_pct:   {c['coverage_denue_pct']}%",
            f"  verified_pct:         {c['verified_pct']}%",
            f"  review_required_pct: {c['review_required_pct']}%",
            f"  out_of_scope_pct:     {c['out_of_scope_pct']}%",
            f"  pending_pct:          {c['pending_pct']}%",
            f"  ambiguous_pct:        {c['ambiguous_pct']}%",
            f"  códigos DENUE sin mapear: {len(self.unmapped_scian_codes)}",
            f"  cola de revisión: {len(self.review_queue)} código(s)",
        ]
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

    # ════════════════════════════════════════════════════════════════════
    # ETAPA 1 — ESQUEMA DE AUTORÍA (Fase 1 ampliada)
    # ════════════════════════════════════════════════════════════════════
    def generate_authoring_template(
        self,
        path: str | Path,
        crosswalk_version: str,
        scian_version: str,
        serio_version: str,
        generated_by: str = "CrosswalkBuilder",
        rows: list[dict] | None = None,
    ) -> Path:
        """
        Genera la plantilla del crosswalk de AUTORÍA (`AUTHORING_SCHEMA`,
        19 columnas). Distinta de `generate_template()` (que sigue
        generando, sin cambios, la plantilla plana original de 3
        columnas) — ambas coexisten y sirven a propósitos distintos.

        Si `rows` se provee, se usa como contenido inicial (por ejemplo,
        para pre-cargar reglas ya decididas); cualquier columna faltante
        se completa con cadena vacía. Los metadatos de versión
        (`crosswalk_version`, `scian_version`, `serio_version`,
        `generated_by`) se inyectan en toda fila que no los traiga ya
        poblados explícitamente — nunca se sobreescribe un valor ya
        capturado por el llamador.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if rows:
            df = pd.DataFrame(rows)
            for col in set(AUTHORING_SCHEMA) - set(df.columns):
                df[col] = ""
            df = df[AUTHORING_SCHEMA]
        else:
            df = pd.DataFrame(columns=AUTHORING_SCHEMA)

        version_defaults = {
            "crosswalk_version": crosswalk_version,
            "scian_version": scian_version,
            "serio_version": serio_version,
            "generated_by": generated_by,
        }
        if len(df):
            for col, default_val in version_defaults.items():
                current = df[col].astype(str).str.strip()
                df[col] = df[col].where(current.ne("") & current.ne("nan"), default_val)

        df.to_csv(path, index=False)
        logger.info("Plantilla de autoría jerárquica creada: %s (%d filas).", path, len(df))
        return path

    def load_authoring(self, path: str | Path) -> pd.DataFrame:
        """Ingesta del crosswalk de autoría. Valida únicamente el esquema
        de columnas (`AUTHORING_SCHEMA`); las reglas de negocio se
        verifican en `validate_authoring()`."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"No se encontró {path}. Genera primero la plantilla con "
                "generate_authoring_template() si aún no existe la tabla de autoría."
            )
        df = pd.read_csv(path, dtype=str).fillna("")
        missing = set(AUTHORING_SCHEMA) - set(df.columns)
        if missing:
            raise ValueError(f"El crosswalk de autoría no cumple AUTHORING_SCHEMA. Faltan columnas: {sorted(missing)}")
        logger.info("Ingesta de crosswalk de autoría completa: %s (%d filas).", path.name, len(df))
        return df

    # ════════════════════════════════════════════════════════════════════
    # ETAPA 2 — VALIDACIÓN DE AUTORÍA (Fases 2–5)
    # ════════════════════════════════════════════════════════════════════
    def validate_authoring(
        self, df: pd.DataFrame, strict: bool = True
    ) -> tuple[pd.DataFrame, "AuthoringValidationReport"]:
        """
        Valida el crosswalk de autoría contra las 5 categorías de reglas
        de negocio acordadas, sin resolver ninguna excepción de forma
        automática (mismo espíritu que `validate()`):

          1. chk_non_numeric      — `scian_codigo` es íntegramente numérico
                                     (rechaza `NonNumericSCIANError`).
          2. chk_valid_length     — la longitud de `scian_codigo` coincide
                                     con la esperada para su `scian_nivel`
                                     (SECTOR=2, SUBSECTOR=3, RAMA=4,
                                     SUBRAMA=5, CLASE=6). También exige que
                                     `scian_nivel` sea uno de los 5 valores
                                     válidos (`InvalidSCIANLengthError`).
          3. chk_unique_scian     — ningún `scian_codigo` se repite en la
                                     tabla, independientemente del nivel
                                     (`DuplicateSCIANError`).
          4. chk_sector_known     — todo `serio_sector` no vacío pertenece
                                     al universo de sectores SERIO
                                     (`UnknownSERIOSectorError`).
          5. chk_state_consistent — la fila cumple el invariante de su
                                     `status` (`StateConsistencyError`):
                                       VERIFIED         → serio_sector no vacío,
                                                          evidence_type ≠ INFERRED,
                                                          mapping_type == EXACT,
                                                          justification no vacía.
                                       REVIEW_REQUIRED,
                                       OUT_OF_SCOPE,
                                       PENDING          → serio_sector vacío.
                                       (cualquier otro status es inválido)

        Además, se ejecuta un detector de ASIGNACIÓN MÚLTIPLE (informativo,
        nunca bloqueante): si el mismo `scian_titulo` (normalizado) aparece
        mapeado a más de un `serio_sector` en filas distintas, se reporta
        en `multiple_semantic_assignments` para revisión humana — nunca se
        resuelve ni se descarta silenciosamente.

        Con `strict=True` (default), si cualquier categoría 1–5 tiene al
        menos una violación se lanza la excepción tipada correspondiente
        (en orden de prioridad: duplicados → sector desconocido → longitud
        inválida → no numérico → inconsistencia de estado), con el detalle
        COMPLETO de todas las categorías falladas en el mensaje — nunca se
        oculta una categoría por reportar solo la primera encontrada.
        Con `strict=False` se retorna el reporte sin lanzar excepción
        (usado internamente por `build_coverage_report()`, que necesita
        poder inspeccionar una tabla de autoría todavía incompleta).
        """
        df = df.copy()
        n = len(df)
        missing = set(AUTHORING_SCHEMA) - set(df.columns)
        if missing:
            raise ValueError(f"El crosswalk de autoría no cumple AUTHORING_SCHEMA. Faltan columnas: {sorted(missing)}")

        scian  = df["scian_codigo"].astype(str).str.strip()
        nivel  = df["scian_nivel"].astype(str).str.strip()
        sector = df["serio_sector"].astype(str).str.strip()

        valid_levels = {lvl.value for lvl in SCIANLevel}

        # 1. chk_non_numeric
        df["chk_non_numeric"] = scian.str.fullmatch(r"\d+").fillna(False)

        # 2. chk_valid_length — independiente de chk_non_numeric a propósito:
        #    la longitud se mide sobre el string tal cual, para que un código
        #    no numérico de longitud correcta dispare ÚNICAMENTE
        #    NonNumericSCIANError y no también InvalidSCIANLengthError (evita
        #    que ambas categorías se disparen siempre juntas por construcción).
        level_ok = nivel.isin(valid_levels)
        expected_len = nivel.map(
            lambda v: SCIAN_LEVEL_DIGITS[SCIANLevel(v)] if v in valid_levels else -1
        )
        df["chk_valid_length"] = level_ok & (scian.str.len() == expected_len)

        # 3. chk_unique_scian
        dup_mask = scian.duplicated(keep=False) & df["chk_non_numeric"]
        df["chk_unique_scian"] = ~dup_mask

        # 4. chk_sector_known
        sector_nonempty = sector.ne("") & sector.ne("nan")
        df["chk_sector_known"] = (~sector_nonempty) | sector.isin(self.serio_sectors)

        # 5. chk_state_consistent
        df["chk_state_consistent"] = df.apply(self._row_state_consistent, axis=1)

        check_cols = [
            "chk_non_numeric", "chk_valid_length", "chk_unique_scian",
            "chk_sector_known", "chk_state_consistent",
        ]
        df["_valid_authoring"] = df[check_cols].all(axis=1)

        violations = {
            "non_numeric_scian":   sorted(set(df.loc[~df["chk_non_numeric"], "scian_codigo"])),
            "invalid_scian_length": sorted(set(df.loc[~df["chk_valid_length"], "scian_codigo"])),
            "duplicate_scian":      sorted(set(df.loc[~df["chk_unique_scian"], "scian_codigo"])),
            "unknown_serio_sector": sorted(set(df.loc[~df["chk_sector_known"], "serio_sector"])),
            "state_consistency": [
                f"{c} (status={s})"
                for c, s in df.loc[~df["chk_state_consistent"], ["scian_codigo", "status"]]
                              .itertuples(index=False)
            ],
        }

        # Detector de asignación múltiple (informativo)
        titulo_to_sectors: dict[str, set] = {}
        for titulo, sec in zip(df["scian_titulo"].astype(str).str.strip().str.lower(), sector):
            if titulo and titulo != "nan" and sec and sec != "nan":
                titulo_to_sectors.setdefault(titulo, set()).add(sec)
        multiple_assignments = sorted(t for t, secs in titulo_to_sectors.items() if len(secs) > 1)

        report = AuthoringValidationReport(
            n_total=n,
            violations=violations,
            multiple_semantic_assignments=multiple_assignments,
            n_valid=int(df["_valid_authoring"].sum()),
            n_invalid=int((~df["_valid_authoring"]).sum()),
        )
        logger.info("\n%s", report.summary())

        if strict:
            active = {k: v for k, v in violations.items() if v}
            if active:
                priority_order = [
                    "duplicate_scian", "unknown_serio_sector",
                    "invalid_scian_length", "non_numeric_scian", "state_consistency",
                ]
                exc_map = {
                    "duplicate_scian":       DuplicateSCIANError,
                    "unknown_serio_sector":  UnknownSERIOSectorError,
                    "invalid_scian_length":  InvalidSCIANLengthError,
                    "non_numeric_scian":     NonNumericSCIANError,
                    "state_consistency":     StateConsistencyError,
                }
                first_key = next(k for k in priority_order if active.get(k))
                detail = "\n".join(f"  - {k}: {v}" for k, v in active.items())
                raise exc_map[first_key](
                    f"validate_authoring() detectó {len(active)} categoría(s) de violación:\n{detail}"
                )
        return df, report

    @staticmethod
    def _row_state_consistent(row: pd.Series) -> bool:
        """Invariante por `status`, evaluado fila por fila (ver docstring
        de `validate_authoring`)."""
        status = str(row.get("status", "")).strip()
        sector = str(row.get("serio_sector", "")).strip()
        evidence = str(row.get("evidence_type", "")).strip()
        mapping = str(row.get("mapping_type", "")).strip()
        justification = str(row.get("justification", "")).strip()
        sector_empty = sector in ("", "nan")
        justification_empty = justification in ("", "nan")

        if status == AuthoringStatus.VERIFIED.value:
            return (
                not sector_empty
                and evidence != EvidenceType.INFERRED.value
                and mapping == MappingType.EXACT.value
                and not justification_empty
            )
        if status in (
            AuthoringStatus.REVIEW_REQUIRED.value,
            AuthoringStatus.OUT_OF_SCOPE.value,
            AuthoringStatus.PENDING.value,
        ):
            return sector_empty
        return False  # status fuera del enum → inconsistente

    # ════════════════════════════════════════════════════════════════════
    # ETAPA 3 — MOTOR DE RESOLUCIÓN JERÁRQUICA (Fase 4)
    # ════════════════════════════════════════════════════════════════════
    def resolve_scian_code(self, scian_code: str, authoring_df: pd.DataFrame) -> "ScianResolution":
        """
        Resuelve un código SCIAN de Clase (6 dígitos) contra la tabla de
        autoría, aplicando el ALGORITMO DE RESOLUCIÓN JERÁRQUICA acordado:

            Clase (6) → Subrama (5) → Rama (4) → Subsector (3) → Sector (2)

        Algoritmo (documentado paso a paso):
          1. Se valida que `scian_code` sea un código de Clase válido
             (6 dígitos numéricos). No se resuelven códigos de otros
             niveles directamente — la resolución siempre parte del nivel
             más desagregado observable en el DENUE.
          2. Se calculan los 5 prefijos ancestros del código (uno por
             nivel, vía `scian_ancestors()`): p.ej. para "311611" —
             CLASE="311611", SUBRAMA="31161", RAMA="3116", SUBSECTOR="311",
             SECTOR="31".
          3. Se filtra `authoring_df` a únicamente las filas con
             `status == VERIFIED` — ninguna fila PENDING, REVIEW_REQUIRED
             u OUT_OF_SCOPE puede resolver un código, sin excepción.
          4. Se recorre `RESOLUTION_ORDER` (CLASE → SUBRAMA → RAMA →
             SUBSECTOR → SECTOR). Para cada nivel se busca una fila
             VERIFIED cuyo `scian_nivel` coincida con el nivel actual y
             cuyo `scian_codigo` coincida con el prefijo de ese nivel.
          5. La PRIMERA coincidencia encontrada — es decir, la de nivel
             más específico disponible — determina el resultado. Nunca se
             combinan, promedian o eligen entre reglas de distintos
             niveles: la más específica siempre gana sobre la más general.
          6. Si ningún nivel tiene una regla VERIFIED aplicable, el código
             se retorna como NO RESUELTO (`resolved=False`) — nunca se
             asigna un sector por default ni se aproxima.

        Retorna un `ScianResolution` con trazabilidad completa: qué nivel
        y qué código de regla ganaron la resolución (útil para auditar
        por qué un establecimiento del DENUE terminó en un sector SERIO
        dado, incluso cuando la regla vino de un ancestro y no del código
        de Clase original).

        Nota de integridad: si `authoring_df` contiene más de una fila
        VERIFIED para el mismo (nivel, código) — lo cual `validate_authoring`
        ya debería haber rechazado como `DuplicateSCIANError` — este método
        lanza `StateConsistencyError` en vez de elegir una arbitrariamente.
        """
        code = str(scian_code).strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(
                f"resolve_scian_code() requiere un código de Clase de 6 dígitos numéricos; recibido: {scian_code!r}"
            )

        ancestors = scian_ancestors(code)
        verified = authoring_df[
            authoring_df["status"].astype(str).str.strip() == AuthoringStatus.VERIFIED.value
        ]

        for level in RESOLUTION_ORDER:
            prefix = ancestors[level]
            match = verified[
                (verified["scian_nivel"].astype(str).str.strip() == level.value)
                & (verified["scian_codigo"].astype(str).str.strip() == prefix)
            ]
            if len(match) > 1:
                raise StateConsistencyError(
                    f"Regla VERIFIED ambigua para {level.value} '{prefix}': "
                    f"{len(match)} filas coinciden (se esperaba biunivocidad; "
                    "ejecuta validate_authoring() para detectar el duplicado)."
                )
            if len(match) == 1:
                row = match.iloc[0]
                return ScianResolution(
                    scian_codigo=code,
                    resolved=True,
                    serio_sector=str(row["serio_sector"]).strip(),
                    matched_level=level,
                    matched_scian_codigo=prefix,
                )
        return ScianResolution(scian_codigo=code, resolved=False)

    def suggest_inferred_rows(
        self,
        authoring_df: pd.DataFrame,
        observed_scian_codes: list[str],
        scian_titles: dict[str, str] | None = None,
        crosswalk_version: str = "",
        scian_version: str = "",
        generated_by: str = "CrosswalkBuilder",
    ) -> pd.DataFrame:
        """
        Acelera la Fase de captura (no la sustituye): para cada código
        SCIAN de Clase observado en el DENUE que TODAVÍA NO TIENE fila
        propia en `authoring_df`, propone una fila candidata usando
        `resolve_scian_code()` sobre las reglas VERIFIED ya existentes en
        niveles superiores.

        Regla dura aplicada aquí (irrenunciable): toda fila propuesta nace
        con `status=PENDING`. Si hubo una regla ancestral VERIFIED
        aplicable, se marca `evidence_type=INFERRED` — pero el candidato de
        sector se documenta ÚNICAMENTE en `notes`, nunca en `serio_sector`,
        porque el invariante de `PENDING` exige `serio_sector` vacío (ver
        `validate_authoring`). Es decir: esta función JAMÁS produce una
        fila `VERIFIED`, ni siquiera cuando encuentra un candidato con alta
        confianza heredado — la conversión a VERIFIED es exclusivamente un
        acto de revisión humana.

        Filas ya presentes en `authoring_df` (a nivel Clase) no se tocan
        ni se duplican — esta función solo llena huecos, nunca sobrescribe
        autoría existente.
        """
        existing_clase_codes = set(
            authoring_df.loc[
                authoring_df["scian_nivel"].astype(str).str.strip() == SCIANLevel.CLASE.value,
                "scian_codigo",
            ].astype(str).str.strip()
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        titles = scian_titles or {}
        new_rows = []

        for code in sorted({str(c).strip() for c in observed_scian_codes}):
            if not re.fullmatch(r"\d{6}", code) or code in existing_clase_codes:
                continue

            resolution = self.resolve_scian_code(code, authoring_df)
            if resolution.resolved:
                evidence = EvidenceType.INFERRED.value
                notes = (
                    f"Candidato heredado de {resolution.matched_level.value} "
                    f"'{resolution.matched_scian_codigo}' → sector SERIO "
                    f"'{resolution.serio_sector}'. Requiere confirmación humana "
                    "explícita (cambiar status a VERIFIED) antes de usarse en "
                    "el lookup compilado."
                )
            else:
                evidence = ""
                notes = "Sin regla ancestral VERIFIED disponible en ningún nivel. Requiere clasificación desde cero."

            row = {col: "" for col in AUTHORING_SCHEMA}
            row.update({
                "scian_codigo": code,
                "scian_nivel": SCIANLevel.CLASE.value,
                "scian_titulo": titles.get(code, ""),
                "evidence_type": evidence,
                "status": AuthoringStatus.PENDING.value,
                "priority": Priority.MEDIUM.value,
                "notes": notes,
                "crosswalk_version": crosswalk_version,
                "scian_version": scian_version,
                "generated_at": now_iso,
                "generated_by": generated_by,
            })
            new_rows.append(row)

        result = pd.DataFrame(new_rows, columns=AUTHORING_SCHEMA)
        logger.info(
            "suggest_inferred_rows(): %d códigos nuevos propuestos (%d con candidato heredado, %d sin ninguna regla ancestral).",
            len(result),
            int((result["evidence_type"] == EvidenceType.INFERRED.value).sum()) if len(result) else 0,
            int((result["evidence_type"] == "").sum()) if len(result) else 0,
        )
        return result

    # ════════════════════════════════════════════════════════════════════
    # ETAPA 4 — COMPILADOR A ARTEFACTO PLANO (puente con el contrato existente)
    # ════════════════════════════════════════════════════════════════════
    def compile_to_flat_lookup(
        self, authoring_df: pd.DataFrame, observed_scian_codes: list[str]
    ) -> pd.DataFrame:
        """
        Compila el crosswalk de autoría jerárquica hacia el ÚNICO formato
        que el resto del pipeline conoce: un `DataFrame` con exactamente
        `CROSSWALK_SCHEMA` (`scian_codigo`, `sector_serio`, `notas`).

        Para cada código de `observed_scian_codes` (los códigos SCIAN de
        6 dígitos realmente presentes en el DENUE que se va a procesar):
          - Se resuelve vía `resolve_scian_code()` (solo reglas VERIFIED,
            precedencia Clase→Subrama→Rama→Subsector→Sector).
          - Si resuelve, se agrega una fila con el sector SERIO resultante
            y una nota de trazabilidad (qué nivel/código de regla lo
            resolvió).
          - Si no resuelve (o el código no tiene formato de Clase válido),
            se omite del artefacto compilado — exactamente el mismo
            comportamiento que ya tiene `apply()`: los códigos sin mapeo
            NUNCA se rellenan con un valor por default, se reportan aparte.

        El `DataFrame` resultante es 100% compatible con `load()` (si se
        persiste a CSV), `validate()`, `build_lookup()` y `apply()` — la
        jerarquía queda completamente encapsulada aquí; ningún consumidor
        del pipeline necesita saber que existió.
        """
        rows = []
        n_resolved = 0
        unresolved: list[str] = []

        for code in sorted({str(c).strip() for c in observed_scian_codes}):
            if not re.fullmatch(r"\d{6}", code):
                unresolved.append(code)
                continue
            resolution = self.resolve_scian_code(code, authoring_df)
            if resolution.resolved:
                rows.append({
                    "scian_codigo": code,
                    "sector_serio": resolution.serio_sector,
                    "notas": (
                        f"Compilado desde autoría jerárquica — regla VERIFIED "
                        f"en nivel {resolution.matched_level.value}, código "
                        f"'{resolution.matched_scian_codigo}'."
                    ),
                })
                n_resolved += 1
            else:
                unresolved.append(code)

        compiled = pd.DataFrame(rows, columns=CROSSWALK_SCHEMA)
        logger.info(
            "compile_to_flat_lookup(): %d/%d códigos SCIAN observados resueltos a un sector SERIO VERIFIED.",
            n_resolved, n_resolved + len(unresolved),
        )
        if unresolved:
            logger.warning(
                "%d códigos SCIAN observados sin regla VERIFIED aplicable tras la compilación: %s",
                len(unresolved), unresolved,
            )
        return compiled

    # ════════════════════════════════════════════════════════════════════
    # ETAPA 5 — MÉTRICAS Y REPORTE DE COBERTURA (Fases 6–7 ampliadas)
    # ════════════════════════════════════════════════════════════════════
    def build_coverage_report(
        self,
        authoring_df: pd.DataFrame,
        observed_scian_codes: list[str],
        scian_catalog_codes: list[str],
        crosswalk_version: str,
        scian_version: str,
        serio_version: str,
        generated_by: str = "CrosswalkBuilder",
    ) -> "CrosswalkCoverageReport":
        """
        Construye el reporte de cobertura completo del activo de datos.

        Dos métricas de cobertura DELIBERADAMENTE separadas (nunca se
        fusionan en una sola cifra):
          - `coverage_catalog_pct`: filas VERIFIED a nivel Clase / tamaño
            del catálogo oficial SCIAN soportado por el proyecto. Mide qué
            tan completo es el activo en abstracto, independientemente del
            DENUE cargado hoy.
          - `coverage_denue_pct`: códigos SCIAN observados en el DENUE
            cargado que SÍ resuelven (vía jerarquía completa, no solo
            filas propias a nivel Clase) contra una regla VERIFIED. Mide
            si ya se puede correr Stage 5 con los datos de hoy.

        `priority_breakdown` da visibilidad operativa por prioridad de
        revisión; `review_queue` extrae directamente las filas
        `REVIEW_REQUIRED` con su prioridad y notas, listas para trabajar.
        """
        df, val_report = self.validate_authoring(authoring_df, strict=False)
        clase_df = df[df["scian_nivel"].astype(str).str.strip() == SCIANLevel.CLASE.value].copy()
        n_clase = len(clase_df)

        catalog_set = {str(c).strip() for c in scian_catalog_codes}
        denue_set = {str(c).strip() for c in observed_scian_codes}

        verified_clase_codes = set(
            clase_df.loc[clase_df["status"] == AuthoringStatus.VERIFIED.value, "scian_codigo"]
        )
        coverage_catalog_pct = (
            round(100 * len(verified_clase_codes & catalog_set) / len(catalog_set), 2)
            if catalog_set else 0.0
        )

        resolved_denue, unmapped_denue = set(), []
        for code in sorted(denue_set):
            if re.fullmatch(r"\d{6}", code) and self.resolve_scian_code(code, df).resolved:
                resolved_denue.add(code)
            else:
                unmapped_denue.append(code)
        coverage_denue_pct = round(100 * len(resolved_denue) / len(denue_set), 2) if denue_set else 0.0

        def _pct(mask) -> float:
            return round(100 * int(mask.sum()) / n_clase, 2) if n_clase else 0.0

        status_col = clase_df["status"]
        coverage = {
            "coverage_catalog_pct":  coverage_catalog_pct,
            "coverage_denue_pct":    coverage_denue_pct,
            "verified_pct":          _pct(status_col == AuthoringStatus.VERIFIED.value),
            "review_required_pct":  _pct(status_col == AuthoringStatus.REVIEW_REQUIRED.value),
            "out_of_scope_pct":     _pct(status_col == AuthoringStatus.OUT_OF_SCOPE.value),
            "pending_pct":          _pct(status_col == AuthoringStatus.PENDING.value),
            "ambiguous_pct":        _pct(clase_df["mapping_type"] == MappingType.AMBIGUOUS.value),
        }

        priority_breakdown = {}
        for p in Priority:
            subset = clase_df[clase_df["priority"] == p.value]
            n_p = len(subset)
            n_v = int((subset["status"] == AuthoringStatus.VERIFIED.value).sum())
            priority_breakdown[p.value] = {
                "count": n_p,
                "verified_pct": round(100 * n_v / n_p, 2) if n_p else 0.0,
            }

        verified_clase = clase_df[clase_df["status"] == AuthoringStatus.VERIFIED.value]
        by_serio_sector = (
            verified_clase.groupby("serio_sector").size().reset_index(name="scian_count")
            .to_dict(orient="records")
            if len(verified_clase) else []
        )

        review_queue = (
            clase_df.loc[
                clase_df["status"] == AuthoringStatus.REVIEW_REQUIRED.value,
                ["scian_codigo", "scian_titulo", "priority", "notes"],
            ].to_dict(orient="records")
        )

        report = CrosswalkCoverageReport(
            metadata={
                "crosswalk_version": crosswalk_version,
                "scian_version": scian_version,
                "serio_version": serio_version,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": generated_by,
            },
            totals={
                "scian_codes_in_official_catalog": len(catalog_set),
                "scian_codes_in_denue_observed": len(denue_set),
                "scian_codes_in_crosswalk": n_clase,
                "serio_sectors_total": len(self.serio_sectors),
            },
            coverage=coverage,
            priority_breakdown=priority_breakdown,
            by_serio_sector=by_serio_sector,
            review_queue=review_queue,
            unmapped_scian_codes=unmapped_denue,
            validation_errors=[f"{k}: {len(v)} caso(s)" for k, v in val_report.violations.items() if v],
        )
        logger.info(
            "Reporte de cobertura generado — coverage_catalog=%.2f%%, coverage_denue=%.2f%%, "
            "verified=%.2f%%, review_required=%.2f%%.",
            coverage_catalog_pct, coverage_denue_pct,
            coverage["verified_pct"], coverage["review_required_pct"],
        )
        return report


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m spatial.warehouse.crosswalk <ruta_salida_template.csv> [sector1,sector2,...]")
        sys.exit(1)

    sectors_arg = sys.argv[2].split(",") if len(sys.argv) > 2 else [f"SEC{i:03d}" for i in range(1, 79)]
    cb = CrosswalkBuilder(serio_sectors=sectors_arg)
    cb.generate_template(sys.argv[1])