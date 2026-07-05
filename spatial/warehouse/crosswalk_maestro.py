# spatial/warehouse/crosswalk_maestro.py
"""
Migración del Crosswalk Maestro SCIAN → SERIO (v0.1) hacia AUTHORING_SCHEMA
============================================================================
El Crosswalk Maestro v0.1 (`Crosswalk_Maestro_SCIAN_SERIO_v0.1.csv`) fue
producido por el equipo de autoría con su propio esquema, orientado a
criterio económico y trazabilidad de la decisión, no al esquema interno
de `CrosswalkBuilder`:

    nivel_scian, codigo_scian, descripcion_scian, sector_serio (nombre),
    confianza (ALTA|MEDIA|BAJA), requiere_revision (SI|NO), justificacion

Este módulo es el ÚNICO lugar del proyecto que conoce ese esquema crudo
(`MASTER_SCHEMA`). Traduce cada fila, de forma determinista y sin
excepciones ocultas, hacia `AUTHORING_SCHEMA` (`spatial.warehouse.crosswalk`)
— el esquema que sí entiende `CrosswalkBuilder.load_authoring()` /
`validate_authoring()`.

No se modifica `crosswalk.py`: este módulo es aditivo y se apoya
únicamente en su contrato público (`AUTHORING_SCHEMA`, los enums, y
`CrosswalkBuilder.generate_authoring_template()` para la escritura final
a CSV, reutilizando su lógica de defaults de versión en vez de
duplicarla).

Regla de traducción (determinista, función únicamente de `confianza` y
`requiere_revision` — nunca de casos particulares por código):

    confianza | requiere_revision | status            | mapping_type | evidence_type | priority
    ----------|--------------------|--------------------|--------------|---------------|----------
    ALTA      | NO                 | VERIFIED           | EXACT        | OFFICIAL      | LOW
    MEDIA     | NO                 | VERIFIED           | EXACT        | EXPERT        | MEDIUM
    MEDIA     | SI                 | REVIEW_REQUIRED    | PARTIAL      | EXPERT        | HIGH
    BAJA      | SI                 | REVIEW_REQUIRED    | AMBIGUOUS    | EXPERT        | HIGH

Cualquier combinación (`confianza`, `requiere_revision`) fuera de esta
tabla se considera un error de datos y se rechaza en el momento
(`ValueError`) — nunca se adivina un status por default, en línea con el
resto del proyecto (ver axioma de unicidad del mapeo sectorial en
`crosswalk.py`).

Para `status = VERIFIED`, `serio_sector`/`serio_nombre` se pueblan con el
código y nombre oficiales (resueltos contra `serio/data/sectores.csv`).
Para `status = REVIEW_REQUIRED`, el invariante de `validate_authoring`
exige `serio_sector` vacío: el nombre candidato (si el Crosswalk Maestro
proponía uno, p.ej. por una discrepancia de vigencia de catálogo) se
conserva únicamente en `notes`, nunca en `serio_sector` — exactamente el
mismo criterio que ya aplica `CrosswalkBuilder.suggest_inferred_rows()`
para candidatos heredados.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from spatial.warehouse.crosswalk import (
    AUTHORING_SCHEMA,
    AuthoringStatus,
    CrosswalkBuilder,
    EvidenceType,
    MappingType,
    Priority,
    SCIANLevel,
)

logger = logging.getLogger("sew.warehouse.crosswalk_maestro")

# Esquema crudo del Crosswalk Maestro v0.1 — contrato de ingesta de ESTE módulo.
MASTER_SCHEMA: list[str] = [
    "nivel_scian", "codigo_scian", "descripcion_scian",
    "sector_serio", "confianza", "requiere_revision", "justificacion",
]

_NIVEL_TO_SCIAN_LEVEL: dict[str, str] = {
    "sector": SCIANLevel.SECTOR.value,
    "subsector": SCIANLevel.SUBSECTOR.value,
    "rama": SCIANLevel.RAMA.value,
    "subrama": SCIANLevel.SUBRAMA.value,
    "clase": SCIANLevel.CLASE.value,
}

# Tabla de traducción determinista (confianza, requiere_revision) → reglas.
# Ver docstring del módulo. Cualquier combinación no listada aquí es un
# error de datos (`ValueError`), nunca un default silencioso.
_TRANSLATION_RULES: dict[tuple[str, str], dict[str, str]] = {
    ("ALTA", "NO"):  {"status": AuthoringStatus.VERIFIED.value,        "mapping_type": MappingType.EXACT.value,     "evidence_type": EvidenceType.OFFICIAL.value, "priority": Priority.LOW.value},
    ("MEDIA", "NO"): {"status": AuthoringStatus.VERIFIED.value,        "mapping_type": MappingType.EXACT.value,     "evidence_type": EvidenceType.EXPERT.value,   "priority": Priority.MEDIUM.value},
    ("MEDIA", "SI"): {"status": AuthoringStatus.REVIEW_REQUIRED.value, "mapping_type": MappingType.PARTIAL.value,   "evidence_type": EvidenceType.EXPERT.value,   "priority": Priority.HIGH.value},
    ("BAJA", "SI"):  {"status": AuthoringStatus.REVIEW_REQUIRED.value, "mapping_type": MappingType.AMBIGUOUS.value, "evidence_type": EvidenceType.EXPERT.value,   "priority": Priority.HIGH.value},
}


class CrosswalkMaestroError(Exception):
    """Error de esquema o de datos al migrar el Crosswalk Maestro crudo."""


def load_master_csv(path: str | Path) -> pd.DataFrame:
    """Ingesta cruda del Crosswalk Maestro v0.1. Valida únicamente que el
    esquema de columnas coincide con `MASTER_SCHEMA` — el resto de las
    reglas de negocio se aplican en `convert_master_to_authoring()`."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el Crosswalk Maestro crudo: {path}")
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    missing = set(MASTER_SCHEMA) - set(df.columns)
    if missing:
        raise CrosswalkMaestroError(
            f"El Crosswalk Maestro no cumple MASTER_SCHEMA. Faltan columnas: {sorted(missing)}"
        )
    logger.info("Ingesta de Crosswalk Maestro crudo completa: %s (%d filas).", path.name, len(df))
    return df


def load_serio_catalog(path: str | Path) -> tuple[list[str], dict[str, str]]:
    """
    Lee `serio/data/sectores.csv` (columnas `scian`, `nombre`) y devuelve:
      - la lista de los 78 códigos SERIO (universo `S`, para construir
        `CrosswalkBuilder(serio_sectors=...)`),
      - el diccionario nombre → código, usado para resolver `sector_serio`
        (que en el Crosswalk Maestro v0.1 viaja como nombre, no como código).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el catálogo de sectores SERIO: {path}")
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    codes = df["scian"].astype(str).str.strip().tolist()
    name_to_code = dict(zip(df["nombre"].astype(str).str.strip(), codes))
    return codes, name_to_code


# Etiqueta legible reutilizada en `source`/`notes` de cada fila traducida.
# No es la misma cosa que `crosswalk_version` (columna de AUTHORING_SCHEMA,
# que se inyecta aparte vía generate_authoring_template) — esta es solo
# para trazabilidad textual dentro del propio contenido de la fila.
CROSSWALK_MAESTRO_VERSION_LABEL = "v0.1"


def _translate_row(row: pd.Series, name_to_code: dict[str, str]) -> dict:
    confianza = str(row["confianza"]).strip().upper()
    revision = str(row["requiere_revision"]).strip().upper()
    key = (confianza, revision)
    if key not in _TRANSLATION_RULES:
        raise CrosswalkMaestroError(
            f"Combinación (confianza={confianza!r}, requiere_revision={revision!r}) sin regla de "
            f"traducción definida para el código {row['codigo_scian']!r}. Combinaciones soportadas: "
            f"{sorted(_TRANSLATION_RULES)}."
        )
    rule = _TRANSLATION_RULES[key]

    nivel_raw = str(row["nivel_scian"]).strip().lower()
    if nivel_raw not in _NIVEL_TO_SCIAN_LEVEL:
        raise CrosswalkMaestroError(
            f"nivel_scian={nivel_raw!r} no reconocido para el código {row['codigo_scian']!r}. "
            f"Valores válidos: {sorted(_NIVEL_TO_SCIAN_LEVEL)}."
        )

    sector_nombre_candidato = str(row["sector_serio"]).strip()
    justificacion = str(row["justificacion"]).strip()
    is_verified = rule["status"] == AuthoringStatus.VERIFIED.value

    if is_verified:
        if not sector_nombre_candidato:
            raise CrosswalkMaestroError(
                f"Fila {row['codigo_scian']!r} es VERIFIED (confianza=ALTA/MEDIA, requiere_revision=NO) "
                "pero no trae sector_serio poblado en el Crosswalk Maestro."
            )
        if sector_nombre_candidato not in name_to_code:
            raise CrosswalkMaestroError(
                f"sector_serio={sector_nombre_candidato!r} (código {row['codigo_scian']!r}) no "
                "corresponde a ningún nombre del catálogo oficial de 78 sectores SERIO."
            )
        serio_sector = name_to_code[sector_nombre_candidato]
        serio_nombre = sector_nombre_candidato
        notes = f"Confianza original en Crosswalk Maestro {CROSSWALK_MAESTRO_VERSION_LABEL}: {confianza}."
    else:
        # Invariante de validate_authoring: REVIEW_REQUIRED exige serio_sector
        # vacío. Si el Crosswalk Maestro proponía un candidato, se conserva
        # únicamente en `notes` — nunca en `serio_sector` (mismo criterio que
        # CrosswalkBuilder.suggest_inferred_rows()).
        serio_sector = ""
        serio_nombre = ""
        if sector_nombre_candidato:
            notes = (
                f"Candidato sugerido en Crosswalk Maestro {CROSSWALK_MAESTRO_VERSION_LABEL}: "
                f"'{sector_nombre_candidato}' (confianza {confianza}). Requiere confirmación humana "
                "explícita (cambiar status a VERIFIED) antes de usarse en el lookup compilado."
            )
        else:
            notes = (
                f"Sin candidato único: {justificacion[:200]}"
                if justificacion else "Sin candidato único propuesto por el Crosswalk Maestro."
            )

    return {
        "scian_codigo": str(row["codigo_scian"]).strip(),
        "scian_nivel": _NIVEL_TO_SCIAN_LEVEL[nivel_raw],
        "scian_titulo": str(row["descripcion_scian"]).strip(),
        "serio_sector": serio_sector,
        "serio_nombre": serio_nombre,
        "evidence_type": rule["evidence_type"],
        "status": rule["status"],
        "priority": rule["priority"],
        "mapping_type": rule["mapping_type"],
        "source": f"Crosswalk Maestro SCIAN→SERIO {CROSSWALK_MAESTRO_VERSION_LABEL} (autoría Lattise)",
        "justification": justificacion,
        "reviewed_by": "",
        "review_date": "",
        "notes": notes,
    }


def convert_master_to_authoring(
    master_df: pd.DataFrame,
    name_to_code: dict[str, str],
) -> pd.DataFrame:
    """
    Traduce el Crosswalk Maestro crudo (`MASTER_SCHEMA`) a una lista de
    filas en `AUTHORING_SCHEMA`, aplicando `_TRANSLATION_RULES` fila por
    fila. No escribe a disco (ver `build_authoring_csv_from_master()` para
    eso) — devuelve únicamente los registros ya traducidos, listos para
    pasarse como `rows=` a `CrosswalkBuilder.generate_authoring_template()`.

    Lanza `CrosswalkMaestroError` ante cualquier fila con una combinación
    (confianza, requiere_revision) no soportada, un `sector_serio` que no
    resuelve contra el catálogo oficial, o un `nivel_scian` desconocido —
    nunca traduce una fila "a medias" ni omite silenciosamente un error.
    """
    missing = set(MASTER_SCHEMA) - set(master_df.columns)
    if missing:
        raise CrosswalkMaestroError(f"master_df no cumple MASTER_SCHEMA. Faltan columnas: {sorted(missing)}")

    rows = [_translate_row(row, name_to_code) for _, row in master_df.iterrows()]
    logger.info(
        "convert_master_to_authoring(): %d filas traducidas (%d VERIFIED, %d REVIEW_REQUIRED).",
        len(rows),
        sum(1 for r in rows if r["status"] == AuthoringStatus.VERIFIED.value),
        sum(1 for r in rows if r["status"] == AuthoringStatus.REVIEW_REQUIRED.value),
    )
    return pd.DataFrame(rows, columns=AUTHORING_SCHEMA)


def build_authoring_csv_from_master(
    master_csv_path: str | Path,
    sectores_csv_path: str | Path,
    output_path: str | Path,
    *,
    crosswalk_version: str,
    scian_version: str,
    serio_version: str,
    generated_by: str = "crosswalk_maestro.build_authoring_csv_from_master",
) -> Path:
    """
    Orquesta la migración completa: lee el Crosswalk Maestro crudo y el
    catálogo de 78 sectores SERIO, traduce cada fila a `AUTHORING_SCHEMA`,
    y escribe el resultado en `output_path` (típicamente
    `spatial.config.CROSSWALK_AUTHORING_CSV`) reutilizando
    `CrosswalkBuilder.generate_authoring_template()` para la escritura —
    este módulo nunca construye el CSV a mano.

    Es la operación que materializa "el mecanismo para cargar
    automáticamente el Crosswalk Maestro" sin que el llamador tenga que
    construir DataFrames por su cuenta: tras ejecutarla una vez,
    `output_path` queda en el formato que `CrosswalkBuilder.load_authoring()`
    consume directamente.
    """
    master_df = load_master_csv(master_csv_path)
    serio_codes, name_to_code = load_serio_catalog(sectores_csv_path)
    authoring_rows = convert_master_to_authoring(master_df, name_to_code).to_dict(orient="records")

    builder = CrosswalkBuilder(serio_sectors=serio_codes)
    out = builder.generate_authoring_template(
        output_path,
        crosswalk_version=crosswalk_version,
        scian_version=scian_version,
        serio_version=serio_version,
        generated_by=generated_by,
        rows=authoring_rows,
    )
    logger.info(
        "Crosswalk Maestro migrado a AUTHORING_SCHEMA: %s (%d filas).", out, len(authoring_rows)
    )
    return out
