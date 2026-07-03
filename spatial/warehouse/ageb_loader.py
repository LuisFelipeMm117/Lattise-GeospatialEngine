# spatial/warehouse/ageb_loader.py
"""
AGEBLoader
==========
Implementa Stage 1 (ingesta), Stage 2 (Validación) y Stage 3 (Normalización)
del pipeline SEW descrito en la Especificación Formal v3.0, Sección 8.

Principio de diseño aplicado — Layer Isolation (Sección 5):
    Validación geométrica y normalización son pasos SEPARADOS y explícitos.
    Ninguna fila se descarta silenciosamente: `validate()` únicamente
    ETIQUETA cada geometría (6 checks independientes) y el descarte, si se
    desea, ocurre en un paso deliberado y aparte: `filter_valid()`.
    Este es el mismo criterio ya usado en `lattise_spatial` (ver memoria de
    proyecto: "silent-failure-free validation, 6 independent geometry checks").

NOTA DE INTEGRACIÓN — lattise_spatial:
    Este loader intenta reutilizar `lattise_spatial` para la ingesta
    multi-formato y la normalización de CRS. Se asumen los siguientes
    símbolos públicos:

        lattise_spatial.io.read_vector(path)          -> gpd.GeoDataFrame
        lattise_spatial.crs.normalize_crs(gdf, epsg)   -> gpd.GeoDataFrame
        lattise_spatial.export.to_geoparquet(gdf, path)-> None

    Si la firma real de tu paquete difiere, ajusta únicamente el bloque
    `_import_lattise_spatial()` de abajo — el resto del módulo no cambia.
    Mientras tanto, el loader es 100% funcional gracias al modo fallback
    nativo (geopandas puro), así que puedes correrlo hoy mismo.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from spatial.config import EPSG_TARGET, AGEB_ID_COL, VALIDATED_DIR, NORMALIZED_DIR

logger = logging.getLogger("sew.warehouse.ageb_loader")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

VALID_GEOM_TYPES = {"Polygon", "MultiPolygon"}


# ══════════════════════════════════════════════════════════════════════════
# Integración opcional con lattise_spatial
# ══════════════════════════════════════════════════════════════════════════
def _import_lattise_spatial():
    """
    Intenta cargar lattise_spatial. Devuelve un objeto con .read_vector,
    .normalize_crs, .to_geoparquet si el import tiene éxito; None si no.
    Ajusta los nombres de import aquí cuando confirmes la API real.
    """
    try:
        import lattise_spatial  # noqa: F401
        from lattise_spatial import io as ls_io          # type: ignore
        from lattise_spatial import crs as ls_crs        # type: ignore
        from lattise_spatial import export as ls_export  # type: ignore

        class _LS:
            read_vector = staticmethod(ls_io.read_vector)
            normalize_crs = staticmethod(ls_crs.normalize_crs)
            to_geoparquet = staticmethod(ls_export.to_geoparquet)

        logger.info("lattise_spatial detectado — usando ingesta/CRS del paquete propio.")
        return _LS()
    except Exception as e:  # ImportError o firma distinta
        logger.warning(
            "lattise_spatial no disponible o con API distinta a la esperada (%s). "
            "Usando fallback nativo geopandas. Esto NO bloquea el pipeline.", e
        )
        return None


_LS = _import_lattise_spatial()


# ══════════════════════════════════════════════════════════════════════════
# Reporte de validación (Stage 2) — sin descarte silencioso
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class AGEBValidationReport:
    n_total: int
    checks: dict = field(default_factory=dict)          # nombre_check -> n_fallas
    n_valid: int = 0
    n_invalid: int = 0
    invalid_ids: list = field(default_factory=list)      # cvegeo con >=1 falla

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"AGEB Validation Report — {self.n_total} geometrías evaluadas",
            f"  válidas:   {self.n_valid}",
            f"  inválidas: {self.n_invalid}",
            "  detalle por check:",
        ]
        for name, n_fail in self.checks.items():
            lines.append(f"    - {name}: {n_fail} fallas")
        return "\n".join(lines)


class AGEBLoader:
    """
    Orquesta Stage 1 → Stage 2 → Stage 3 para el Marco Geoestadístico (AGEB)
    de INEGI. Ver spatial/config.py para rutas y CRS objetivo.
    """

    def __init__(self, epsg_target: int = EPSG_TARGET, id_col: str = AGEB_ID_COL):
        self.epsg_target = epsg_target
        self.id_col = id_col

    # ────────────────────────────────────────────────────────────────────
    # Stage 1 — Ingesta (Raw Data Layer)
    # ────────────────────────────────────────────────────────────────────
    def load(self, path: str | Path) -> gpd.GeoDataFrame:
        """
        Ingesta un shapefile/GPKG/GeoJSON de AGEBs. No modifica ni valida
        la geometría — es una lectura fiel del insumo raw (Immutable Raw Data).
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"No se encontró el archivo AGEB: {path}")

        if _LS is not None:
            gdf = _LS.read_vector(path)
        else:
            gdf = gpd.read_file(path)

        logger.info("Ingesta completa: %s (%d registros, CRS=%s)", path.name, len(gdf), gdf.crs)
        return gdf

    # ────────────────────────────────────────────────────────────────────
    # Stage 2 — Validación (6 checks independientes, sin descarte)
    # ────────────────────────────────────────────────────────────────────
    def validate(self, gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, AGEBValidationReport]:
        """
        Etiqueta cada geometría con 6 checks independientes. NO elimina
        ninguna fila — eso ocurre, si se desea, en `filter_valid()`.

        Checks:
          1. geom_not_null      — geometría no es None
          2. geom_not_empty     — geometría no está vacía
          3. geom_is_valid      — sin auto-intersecciones (shapely .is_valid)
          4. geom_type_ok       — tipo Polygon/MultiPolygon
          5. area_positive      — área > 0
          6. id_unique          — cvegeo no duplicado dentro del dataset
        """
        gdf = gdf.copy()
        n = len(gdf)

        def _is_valid_geom(g: Optional[BaseGeometry]) -> bool:
            return bool(g is not None and not g.is_empty and g.is_valid)

        gdf["chk_geom_not_null"]  = gdf.geometry.notna()
        gdf["chk_geom_not_empty"] = gdf.geometry.apply(lambda g: g is not None and not g.is_empty)
        gdf["chk_geom_is_valid"]  = gdf.geometry.apply(lambda g: g is not None and not g.is_empty and g.is_valid)
        gdf["chk_geom_type_ok"]   = gdf.geometry.apply(
            lambda g: g is not None and not g.is_empty and g.geom_type in VALID_GEOM_TYPES
        )
        # Área solo se puede evaluar de forma confiable si la geometría es válida
        gdf["chk_area_positive"] = gdf.apply(
            lambda r: bool(_is_valid_geom(r.geometry) and r.geometry.area > 0), axis=1
        )

        if self.id_col in gdf.columns:
            dup_mask = gdf[self.id_col].duplicated(keep=False)
            gdf["chk_id_unique"] = ~dup_mask
        else:
            logger.warning("Columna id '%s' no encontrada — check id_unique se marca como fallido para todas las filas.", self.id_col)
            gdf["chk_id_unique"] = False

        check_cols = [
            "chk_geom_not_null", "chk_geom_not_empty", "chk_geom_is_valid",
            "chk_geom_type_ok", "chk_area_positive", "chk_id_unique",
        ]
        gdf["_valid_geometry"] = gdf[check_cols].all(axis=1)

        report = AGEBValidationReport(
            n_total=n,
            checks={c: int((~gdf[c]).sum()) for c in check_cols},
            n_valid=int(gdf["_valid_geometry"].sum()),
            n_invalid=int((~gdf["_valid_geometry"]).sum()),
            invalid_ids=(
                gdf.loc[~gdf["_valid_geometry"], self.id_col].astype(str).tolist()
                if self.id_col in gdf.columns else []
            ),
        )
        logger.info("\n%s", report.summary())
        return gdf, report

    def filter_valid(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Paso EXPLÍCITO y deliberado de descarte. Requiere que `validate()`
        se haya ejecutado antes (columna `_valid_geometry` presente).
        """
        if "_valid_geometry" not in gdf.columns:
            raise ValueError("Ejecuta validate() antes de filter_valid(); no hay descarte implícito.")
        n_before = len(gdf)
        gdf_out = gdf[gdf["_valid_geometry"]].copy()
        logger.info("filter_valid(): %d → %d registros (%d descartados explícitamente)",
                    n_before, len(gdf_out), n_before - len(gdf_out))
        return gdf_out

    # ────────────────────────────────────────────────────────────────────
    # Stage 3 — Normalización
    # ────────────────────────────────────────────────────────────────────
    def normalize(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        - Reproyección forzada al CRS objetivo (EPSG:6372).
        - Homologación de nombres de columnas a minúsculas.
        - Cálculo explícito de área (m²), perímetro (m) y centroide
          (lon/lat en EPSG:4326, para consumo directo en mapas/joins).
        """
        gdf = gdf.copy()
        gdf.columns = [str(c).strip().lower() for c in gdf.columns]

        if _LS is not None:
            gdf = _LS.normalize_crs(gdf, self.epsg_target)
        else:
            if gdf.crs is None:
                raise ValueError("El GeoDataFrame no tiene CRS definido; no se puede reproyectar de forma segura.")
            gdf = gdf.to_crs(epsg=self.epsg_target)

        gdf["area_m2"]     = gdf.geometry.area
        gdf["perimeter_m"] = gdf.geometry.length

        centroids_geo = gdf.geometry.centroid.to_crs(epsg=4326)
        gdf["centroid_lon"] = centroids_geo.x
        gdf["centroid_lat"] = centroids_geo.y

        logger.info("Normalización completa: CRS=EPSG:%d, %d registros.", self.epsg_target, len(gdf))
        return gdf

    # ────────────────────────────────────────────────────────────────────
    # Export
    # ────────────────────────────────────────────────────────────────────
    def to_geoparquet(self, gdf: gpd.GeoDataFrame, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if _LS is not None:
            _LS.to_geoparquet(gdf, path)
        else:
            gdf.to_parquet(path)
        logger.info("Exportado GeoParquet: %s", path)
        return path

    # ────────────────────────────────────────────────────────────────────
    # Pipeline completo Stage 1→3
    # ────────────────────────────────────────────────────────────────────
    def run(
        self,
        path: str | Path,
        drop_invalid: bool = False,
        save_intermediate: bool = True,
    ) -> dict:
        """
        Ejecuta el pipeline completo de ingesta. `drop_invalid=False` por
        defecto — el descarte de geometrías inválidas es una decisión
        explícita del usuario, nunca automática.
        """
        raw = self.load(path)
        validated, report = self.validate(raw)

        if save_intermediate:
            VALIDATED_DIR.mkdir(parents=True, exist_ok=True)
            out_val = VALIDATED_DIR / f"{Path(path).stem}_validated.parquet"
            report.to_json(VALIDATED_DIR / f"{Path(path).stem}_report.json")
            # Se guarda el detalle completo (incluye columnas chk_* y _valid_geometry)
            # para trazabilidad de auditoría — nada se descarta en este punto.
            validated.to_parquet(out_val)

        working = self.filter_valid(validated) if drop_invalid else validated

        normalized = self.normalize(working)

        if save_intermediate:
            NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
            out_norm = NORMALIZED_DIR / f"{Path(path).stem}_normalized.parquet"
            self.to_geoparquet(normalized, out_norm)

        return {"raw": raw, "validated": validated, "report": report, "normalized": normalized}


# ══════════════════════════════════════════════════════════════════════════
# CLI de prueba rápida
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python -m spatial.warehouse.ageb_loader <ruta_ageb.shp|.gpkg|.geojson>")
        sys.exit(1)

    loader = AGEBLoader()
    result = loader.run(sys.argv[1])
    print(result["report"].summary())
