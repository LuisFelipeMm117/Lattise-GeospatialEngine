# spatial/config.py
"""
Configuración centralizada del Spatial Economic Warehouse (SEW) Engine.
Single Source of Truth para rutas, CRS y constantes del pipeline.
Ver: SEW_Engine_Scientific_Specification_v3.pdf, Sección 5 (Design Principles).
"""
from pathlib import Path

# ── CRS objetivo (obligatorio en todo el pipeline, Stage 3) ────────────────
# EPSG:6372 — México ITRF2008 / LCC. Debe coincidir con lattise_spatial.
EPSG_TARGET = 6372

# ── Sectores SERIO ───────────────────────────────────────────────────────
N_SECTORES_SERIO = 78

# ── Estructura de directorios (Data Contracts, Sección 8) ──────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR       = BASE_DIR / "data"
RAW_DIR        = DATA_DIR / "raw"          # Stage 1 — inmutable
VALIDATED_DIR  = DATA_DIR / "validated"    # Stage 2 — output de AGEBLoader.validate()
NORMALIZED_DIR = DATA_DIR / "normalized"   # Stage 3 — output de AGEBLoader.normalize()
INTEGRATED_DIR = DATA_DIR / "integrated"   # Stage 4 — post Spatial Join (g, s)
WAREHOUSE_DIR  = DATA_DIR / "warehouse"    # Stage 5 — warehouse.parquet + metadata.json
QA_DIR         = DATA_DIR / "qa"           # Stage 6 — quality_report.json/pdf
SSD_DIR        = DATA_DIR / "ssd"          # Stage 7 — shock_ageb.parquet

for _d in (RAW_DIR, VALIDATED_DIR, NORMALIZED_DIR, INTEGRATED_DIR,
           WAREHOUSE_DIR, QA_DIR, SSD_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Nombres de archivo estándar ─────────────────────────────────────────────
WAREHOUSE_PARQUET = WAREHOUSE_DIR / "warehouse.parquet"
WAREHOUSE_METADATA = WAREHOUSE_DIR / "metadata.json"
QUALITY_REPORT_JSON = QA_DIR / "quality_report.json"

# ── Columna identificadora de AGEB (INEGI Marco Geoestadístico) ────────────
AGEB_ID_COL = "cvegeo"

# ── Crosswalk SCIAN → SERIO (activo de datos, autoría jerárquica) ──────────
# Ver spatial/warehouse/crosswalk.py — arquitectura:
#     Autoría jerárquica → Validación → Compilación → Lookup plano → WarehouseBuilder
CROSSWALK_DIR           = DATA_DIR / "crosswalk"
CROSSWALK_RAW_DIR        = CROSSWALK_DIR / "raw"          # insumo inmutable (Crosswalk Maestro v0.x tal cual se entrega)
CROSSWALK_AUTHORING_CSV = CROSSWALK_DIR / "crosswalk_autoria_scian_serio.csv"  # activo editable — AUTHORING_SCHEMA
CROSSWALK_COMPILED_CSV  = CROSSWALK_DIR / "crosswalk_scian_serio.csv"      # único artefacto que consume WarehouseBuilder
CROSSWALK_REPORT_JSON   = CROSSWALK_DIR / "crosswalk_report.json"

# Crosswalk Maestro v0.1 — insumo crudo tal como lo entrega el equipo de
# autoría (esquema propio por criterio económico: nivel/código/descripción/
# sector_serio/confianza/requiere_revision/justificación). Se migra a
# AUTHORING_SCHEMA vía spatial.warehouse.crosswalk_maestro antes de entrar
# al pipeline oficial (ver scripts/build_crosswalk_maestro.py). Nunca se
# edita in situ: es un snapshot versionado, igual que RAW_DIR (Stage 1).
CROSSWALK_MASTER_RAW_CSV = CROSSWALK_RAW_DIR / "Crosswalk_Maestro_SCIAN_SERIO_v0.1.csv"

# Catálogo de los 78 sectores SERIO (código, nombre) — universo S y fuente
# de la resolución nombre → código usada por la migración del Crosswalk Maestro.
SERIO_SECTORES_CSV = BASE_DIR / "serio" / "data" / "sectores.csv"

for _d in (CROSSWALK_DIR, CROSSWALK_RAW_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Versionamiento del activo de datos (AUTHORING_SCHEMA) ──────────────────
# Single Source of Truth para las columnas *_version que viajan en cada fila
# de autoría — evita que cada script/caller repita estos literales.
CROSSWALK_VERSION = "v0.1"
SCIAN_VERSION      = "SCIAN-2018 (base SERIO); estructura verificada contra fixture INEGI SCIAN-2023 — ver README de spatial/warehouse"
SERIO_VERSION      = "SERIO-78-2018"