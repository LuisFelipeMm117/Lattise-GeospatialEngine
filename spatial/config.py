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
