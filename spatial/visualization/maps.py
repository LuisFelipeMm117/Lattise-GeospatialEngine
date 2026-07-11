# spatial/visualization/maps.py
"""
Visualization — Capa de Visualización (Especificación Formal v3.0, Sección
8, Stage 9).

Responsabilidad:
    INPUT   (Sección 8, Stage 9): archivos espaciales vectoriales ya
            procesados por el motor econométrico SEE (Stage 8B/8C, CERRADOS
            — `spatial.simulation.operator.propagate()` /
            `spatial.simulation.engine.run_simulation_engine()`).
    PROCESO: renderizado de mapas coropléticos de alta resolución
            (choque directo, impacto propagado, impacto indirecto u
            cualquier otra columna numérica), exportación de capas
            geoespaciales ligeras y preparación de datos para paneles
            interactivos.
    OUTPUT  (Sección 8, Stage 9): "mapas analíticos listos para
            publicación académica (PNG), capas geoespaciales ligeras
            (GeoJSON) y cuadros de mando interactivos (Dashboards)".

Este módulo:
    - NO recalcula nada del SEW/SSD/SEE (Stages 1-8) — es un consumidor
      puro de cualquier `GeoDataFrame` con geometría y una columna
      numérica, sin acoplarse a un origen concreto (`ScenarioResult`,
      `run_simulation_engine()`, o cualquier otro). Mismo criterio de
      agnosticismo de origen ya usado en `allocation.allocator` respecto
      del vector de choque ΔX_s.
    - NO renderiza interactividad (mapas/paneles Plotly, Streamlit,
      etc.) — eso pertenece a la capa de aplicación (`app/`). Aquí solo
      se producen artefactos deterministas (PNG, GeoJSON en disco) y
      estructuras de datos ya preparadas (GeoJSON + valores en memoria)
      para que esa capa las consuma sin tener que reproyectar ni
      recalcular estadísticos por su cuenta.
    - Nunca descarta en silencio: AGEBs sin geometría conocida (p. ej.
      `geometry = None`, caso ya documentado en
      `simulation.engine._build_result_geodataframe` para AGEBs que
      nunca recibieron reparto ω en ningún sector) se excluyen
      explícitamente del artefacto geoespacial y se reportan en
      `VisualizationReport.agebs_sin_geometria` — nunca se omiten sin
      dejar rastro.
    - Valores nulos (`NaN`) en la columna a visualizar, con geometría
      válida, NO se excluyen del mapa: se dibujan con un estilo
      distintivo (`missing_kwds`) en vez de desaparecer silenciosamente
      del lienzo.

NOTA — corrección respecto al estado previo del stub:
    La versión anterior de este archivo declaraba depender de
    `spatial.allocation.simulation` (el módulo de estimación
    econométrica SAR/SEM/SDM, aún PENDIENTE, bloqueado por el panel
    DENUE). Esa dependencia no es correcta ni necesaria: el propio
    contrato de datos de Stage 9 (Sección 8) solo exige "archivos
    espaciales vectoriales procesados por el motor econométrico SEE",
    y ese insumo ya existe hoy — lo produce el operador de propagación
    determinista de Stage 8B/8C (CERRADO). Este módulo no depende de
    `spatial.allocation.simulation` en absoluto.

Depende de (solo como consumidor genérico de su forma de datos, nunca
como caller de sus etapas internas):
    - geopandas.GeoDataFrame con geometría + una columna numérica,
      cualquiera sea su origen dentro de Stage 8 (CERRADO).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from spatial.config import AGEB_ID_COL, VISUALIZATION_DIR

logger = logging.getLogger("sew.visualization.maps")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

# ── CRS de salida obligatorio para artefactos web/GeoJSON ──────────────────
# RFC 7946 exige WGS84 (EPSG:4326) para GeoJSON. El pipeline interno trabaja
# en EPSG:6372 (Sección 8, Stage 3) — la reproyección ocurre únicamente en
# esta capa de salida, nunca aguas arriba (mismo criterio ya documentado en
# la memoria de proyecto: "EPSG:6372 throughout pipeline; EPSG:4326 for
# Plotly rendering").
GEOJSON_CRS = "EPSG:4326"

DEFAULT_DPI = 300
DEFAULT_CMAP = "RdYlBu_r"
DEFAULT_FIGSIZE = (10.0, 10.0)
DEFAULT_MISSING_COLOR = "#e5e7eb"

VALID_CLASSIFICATIONS = ("linear", "quantiles", "equal_interval")


# ══════════════════════════════════════════════════════════════════════════
# Excepciones explícitas — nunca se renderiza ni exporta en silencio
# ══════════════════════════════════════════════════════════════════════════
class ColumnNotFoundError(ValueError):
    """`value_col` (o alguna columna de `columns`) no existe en el GeoDataFrame recibido."""


class EmptyGeometryError(ValueError):
    """Ningún feature del GeoDataFrame tiene geometría válida para renderizar/exportar."""


class InvalidClassificationError(ValueError):
    """`classification` no pertenece a `VALID_CLASSIFICATIONS`."""


# ══════════════════════════════════════════════════════════════════════════
# Reporte de visualización — mismo patrón que el resto del SEW/SSD/SEE
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class VisualizationReport:
    tipo: str                      # "choropleth_png" | "geojson_export" | "dashboard_layer"
    value_col: str
    n_features_total: int
    n_features_incluidos: int = 0
    n_features_sin_geometria: int = 0
    agebs_sin_geometria: list = field(default_factory=list)
    n_valores_nulos: int = 0
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    value_mean: Optional[float] = None
    classification: Optional[str] = None
    n_classes: Optional[int] = None
    crs_salida: Optional[str] = None
    output_path: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Visualization Report ({self.tipo}) — columna '{self.value_col}', "
            f"{self.n_features_total} features evaluados",
            f"  incluidos en el artefacto: {self.n_features_incluidos}",
            f"  excluidos por falta de geometría: {self.n_features_sin_geometria}",
        ]
        if self.n_valores_nulos:
            lines.append(f"  valores nulos (geometría sí incluida, dibujados como 'sin dato'): {self.n_valores_nulos}")
        if self.value_min is not None:
            lines.append(
                f"  rango de valores: [{self.value_min:.4g}, {self.value_max:.4g}] "
                f"(media {self.value_mean:.4g})"
            )
        if self.classification:
            lines.append(f"  clasificación: {self.classification} ({self.n_classes} clases)")
        if self.crs_salida:
            lines.append(f"  CRS de salida: {self.crs_salida}")
        if self.agebs_sin_geometria:
            lines.append(f"  ids sin geometría (muestra): {self.agebs_sin_geometria[:10]}")
        if self.output_path:
            lines.append(f"  artefacto escrito en: {self.output_path}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Utilidad interna — separación explícita geometría válida / ausente
# ══════════════════════════════════════════════════════════════════════════
def _split_by_geometry(
    gdf: gpd.GeoDataFrame, id_col: str
) -> tuple[gpd.GeoDataFrame, list]:
    """
    Separa `gdf` en (con_geometria, ids_sin_geometria). Una geometría se
    considera ausente si es `None` o si `is_empty` — nunca se infiere ni
    interpola una geometría faltante (mismo criterio que
    `simulation.engine._build_result_geodataframe`, que ya deja
    `geometry = None` para AGEBs sin ningún reparto ω).
    """
    geom_valida = gdf.geometry.notna() & ~gdf.geometry.is_empty
    con_geometria = gdf.loc[geom_valida].copy()
    sin_geometria_ids = gdf.loc[~geom_valida, id_col].astype(str).tolist() if id_col in gdf.columns else []
    return con_geometria, sin_geometria_ids


def _validate_columns(gdf: gpd.GeoDataFrame, required: Sequence[str]) -> None:
    faltantes = [c for c in required if c not in gdf.columns]
    if faltantes:
        raise ColumnNotFoundError(
            f"Columna(s) {faltantes} no encontrada(s) en el GeoDataFrame recibido. "
            f"Columnas disponibles: {list(gdf.columns)}"
        )


def _value_stats(series: pd.Series) -> dict:
    valores = series.dropna()
    if valores.empty:
        return {"value_min": None, "value_max": None, "value_mean": None}
    return {
        "value_min": float(valores.min()),
        "value_max": float(valores.max()),
        "value_mean": float(valores.mean()),
    }


def _classify(series: pd.Series, classification: str, n_classes: int) -> Optional[pd.Series]:
    """
    Discretiza `series` en `n_classes` intervalos, sin depender de
    `mapclassify` (no es una dependencia del proyecto — ver
    requirements.txt). `classification == "linear"` devuelve `None`
    (colormap continuo, sin discretizar).
    """
    if classification == "linear":
        return None
    if classification == "quantiles":
        try:
            return pd.qcut(series, q=n_classes, duplicates="drop")
        except ValueError:
            # Muy pocos valores distintos para `n_classes` cuantiles —
            # se reporta vía logger, nunca se falla en silencio ni se
            # sustituye por un resultado inventado.
            logger.warning(
                "No fue posible construir %d cuantiles distintos para esta serie "
                "(valores insuficientes/duplicados) — usando equal_interval como respaldo.",
                n_classes,
            )
            return pd.cut(series, bins=n_classes)
    if classification == "equal_interval":
        return pd.cut(series, bins=n_classes)
    raise InvalidClassificationError(
        f"classification='{classification}' no reconocida. Valores válidos: {VALID_CLASSIFICATIONS}"
    )


# ══════════════════════════════════════════════════════════════════════════
# Choropleth — PNG de alta resolución, listo para publicación académica
# ══════════════════════════════════════════════════════════════════════════
def render_choropleth(
    gdf: gpd.GeoDataFrame,
    value_col: str,
    output_path: Union[str, Path],
    *,
    id_col: str = AGEB_ID_COL,
    title: Optional[str] = None,
    legend_label: Optional[str] = None,
    cmap: str = DEFAULT_CMAP,
    classification: str = "quantiles",
    n_classes: int = 7,
    figsize: tuple = DEFAULT_FIGSIZE,
    dpi: int = DEFAULT_DPI,
    missing_color: str = DEFAULT_MISSING_COLOR,
) -> tuple[Path, VisualizationReport]:
    """
    Renderiza un mapa coroplético estático de `value_col` sobre la
    geometría de `gdf` y lo guarda en `output_path` (PNG, `dpi` por
    defecto 300 — resolución de publicación académica).

    No recalcula `value_col`: se asume ya producida por Stage 8B/8C
    (p. ej. `shock_directo`, `impacto_propagado`, `impacto_indirecto`
    del `GeoDataFrame` de `simulation.engine.run_simulation_engine()`,
    o cualquier serie que el caller haya unido a una geometría AGEB).

    Filas sin geometría se excluyen del lienzo y se reportan
    (`VisualizationReport.agebs_sin_geometria`); filas con geometría
    pero `value_col` nulo se dibujan con `missing_color` en vez de
    desaparecer.

    `classification` controla la discretización de color:
        - "linear"         : colormap continuo (sin discretizar).
        - "quantiles"       : `n_classes` cuantiles (por defecto).
        - "equal_interval"  : `n_classes` intervalos de igual amplitud.

    Devuelve `(Path(output_path), VisualizationReport)`.
    """
    if classification not in VALID_CLASSIFICATIONS:
        raise InvalidClassificationError(
            f"classification='{classification}' no reconocida. Valores válidos: {VALID_CLASSIFICATIONS}"
        )
    _validate_columns(gdf, [value_col])

    con_geometria, sin_geometria_ids = _split_by_geometry(gdf, id_col)
    if con_geometria.empty:
        raise EmptyGeometryError(
            f"Ningún feature de los {len(gdf)} recibidos tiene geometría válida — "
            "no hay nada que renderizar."
        )

    stats = _value_stats(con_geometria[value_col])
    n_nulos = int(con_geometria[value_col].isna().sum())

    fig, ax = plt.subplots(figsize=figsize)
    plot_col = value_col
    scheme_series = _classify(con_geometria[value_col], classification, n_classes)

    if scheme_series is not None:
        plot_col = f"__{value_col}_clase"
        con_geometria = con_geometria.copy()
        con_geometria[plot_col] = scheme_series.astype(str)
        con_geometria.loc[con_geometria[value_col].isna(), plot_col] = np.nan

    con_geometria.plot(
        column=plot_col,
        cmap=cmap,
        linewidth=0.1,
        edgecolor="#94a3b8",
        ax=ax,
        legend=True,
        categorical=scheme_series is not None,
        missing_kwds={"color": missing_color, "edgecolor": "#cbd5e1", "label": "Sin dato"},
        legend_kwds=(
            {"title": legend_label or value_col, "loc": "lower left", "fontsize": 8, "frameon": False}
            if scheme_series is not None
            else {"label": legend_label or value_col, "shrink": 0.6}
        ),
    )
    ax.set_axis_off()
    ax.set_title(title or f"Distribución territorial — {value_col}", fontsize=13, fontweight="bold")
    fig.tight_layout()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    report = VisualizationReport(
        tipo="choropleth_png",
        value_col=value_col,
        n_features_total=len(gdf),
        n_features_incluidos=len(con_geometria),
        n_features_sin_geometria=len(sin_geometria_ids),
        agebs_sin_geometria=sin_geometria_ids,
        n_valores_nulos=n_nulos,
        classification=classification,
        n_classes=n_classes if classification != "linear" else None,
        output_path=str(output_path),
        **stats,
    )
    logger.info("Choropleth escrito en %s (%d features incluidos).", output_path, len(con_geometria))
    return output_path, report


# ══════════════════════════════════════════════════════════════════════════
# GeoJSON — capa geoespacial ligera, EPSG:4326 obligatorio (RFC 7946)
# ══════════════════════════════════════════════════════════════════════════
def export_geojson(
    gdf: gpd.GeoDataFrame,
    output_path: Union[str, Path],
    *,
    id_col: str = AGEB_ID_COL,
    columns: Optional[Sequence[str]] = None,
    simplify_tolerance: Optional[float] = None,
) -> tuple[Path, VisualizationReport]:
    """
    Exporta `gdf` como GeoJSON en `output_path`, reproyectado a
    EPSG:4326 (obligatorio para GeoJSON — RFC 7946; el pipeline interno
    trabaja en EPSG:6372, Sección 8 Stage 3).

    `columns`: subconjunto de columnas (además de `id_col`) a incluir
    como propiedades — si se omite, se conservan todas las columnas no
    geométricas presentes. Si se pide una columna inexistente, se
    lanza `ColumnNotFoundError` en vez de omitirla en silencio.

    `simplify_tolerance`: si se aporta, simplifica la geometría
    (`preserve_topology=True`) ANTES de reproyectar — la tolerancia se
    interpreta en las unidades del CRS de origen de `gdf` (metros, si
    ya está en EPSG:6372), para que el valor sea interpretable
    físicamente. Reduce el peso del archivo para consumo web/dashboard
    ("capas geoespaciales ligeras", Stage 9).

    Filas sin geometría válida se excluyen y se reportan (nunca se
    emiten como `Feature` con `geometry: null` de forma implícita).
    """
    id_present = id_col in gdf.columns
    required = [id_col] if id_present else []
    if columns:
        required += list(columns)
    if required:
        _validate_columns(gdf, required)

    con_geometria, sin_geometria_ids = _split_by_geometry(gdf, id_col if id_present else gdf.columns[0])
    if con_geometria.empty:
        raise EmptyGeometryError(
            f"Ningún feature de los {len(gdf)} recibidos tiene geometría válida — nada que exportar."
        )

    if columns is not None:
        keep = ([id_col] if id_present else []) + list(columns) + ["geometry"]
        con_geometria = con_geometria[keep].copy()

    if simplify_tolerance is not None:
        con_geometria = con_geometria.copy()
        con_geometria["geometry"] = con_geometria.geometry.simplify(
            simplify_tolerance, preserve_topology=True
        )

    con_geometria_4326 = con_geometria.to_crs(GEOJSON_CRS)
    if id_present:
        con_geometria_4326 = con_geometria_4326.set_index(id_col)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con_geometria_4326.to_file(output_path, driver="GeoJSON")

    value_col_reportado = columns[0] if columns else "(todas las columnas)"
    stats = (
        _value_stats(con_geometria[columns[0]])
        if columns and pd.api.types.is_numeric_dtype(con_geometria[columns[0]])
        else {"value_min": None, "value_max": None, "value_mean": None}
    )

    report = VisualizationReport(
        tipo="geojson_export",
        value_col=value_col_reportado,
        n_features_total=len(gdf),
        n_features_incluidos=len(con_geometria),
        n_features_sin_geometria=len(sin_geometria_ids),
        agebs_sin_geometria=sin_geometria_ids,
        crs_salida=GEOJSON_CRS,
        output_path=str(output_path),
        **stats,
    )
    logger.info("GeoJSON escrito en %s (%d features, CRS %s).", output_path, len(con_geometria), GEOJSON_CRS)
    return output_path, report


# ══════════════════════════════════════════════════════════════════════════
# Dashboard layer — estructura en memoria para paneles interactivos
# ══════════════════════════════════════════════════════════════════════════
def build_dashboard_layer(
    gdf: gpd.GeoDataFrame,
    value_col: str,
    *,
    id_col: str = AGEB_ID_COL,
    columns: Optional[Sequence[str]] = None,
    simplify_tolerance: Optional[float] = None,
) -> tuple[dict, VisualizationReport]:
    """
    Prepara, en memoria (sin escribir a disco), la estructura que
    consume un panel interactivo (p. ej. `px.choropleth_mapbox` en la
    capa de aplicación Streamlit): un `FeatureCollection` GeoJSON en
    EPSG:4326 indexado por `id_col`, el diccionario `{id: valor}` de
    `value_col` y estadísticos básicos — para que la capa de
    aplicación no tenga que reproyectar ni recalcular nada por su
    cuenta (Layer Isolation: este módulo prepara datos, no renderiza
    interactividad).

    Devuelve `(layer_dict, VisualizationReport)` donde `layer_dict` es:

        {
          "type": "FeatureCollection",
          "features": [...],       # EPSG:4326, id = id_col
          "value_col": value_col,
          "values": {id: valor, ...},
          "stats": {"min": ..., "max": ..., "mean": ...},
        }
    """
    _validate_columns(gdf, [value_col])
    extra_cols = [c for c in (columns or []) if c != value_col]
    cols_to_keep = [value_col] + extra_cols

    geojson_path_cols = cols_to_keep
    con_geometria, sin_geometria_ids = _split_by_geometry(gdf, id_col)
    if con_geometria.empty:
        raise EmptyGeometryError(
            f"Ningún feature de los {len(gdf)} recibidos tiene geometría válida — nada que preparar."
        )

    keep = [id_col] + geojson_path_cols + ["geometry"]
    _validate_columns(con_geometria, keep[:-1])
    subset = con_geometria[keep].copy()

    if simplify_tolerance is not None:
        subset["geometry"] = subset.geometry.simplify(simplify_tolerance, preserve_topology=True)

    subset_4326 = subset.to_crs(GEOJSON_CRS).set_index(id_col)
    feature_collection = json.loads(subset_4326.to_json())

    stats = _value_stats(con_geometria[value_col])
    values = con_geometria.set_index(id_col)[value_col]
    # `.astype(object)` es necesario: una Series float64 no puede contener
    # `None` (se recasteaba a NaN en silencio) — con dtype object sí, y
    # `NaN` se traduce explícitamente a `None` para que el consumidor
    # (dashboard/JSON) reciba un nulo real, no un float NaN no serializable.
    values = values.astype(object).where(pd.notna(values), None)

    layer = {
        "type": "FeatureCollection",
        "features": feature_collection["features"],
        "value_col": value_col,
        "values": values.to_dict(),
        "stats": {"min": stats["value_min"], "max": stats["value_max"], "mean": stats["value_mean"]},
    }

    report = VisualizationReport(
        tipo="dashboard_layer",
        value_col=value_col,
        n_features_total=len(gdf),
        n_features_incluidos=len(con_geometria),
        n_features_sin_geometria=len(sin_geometria_ids),
        agebs_sin_geometria=sin_geometria_ids,
        n_valores_nulos=int(con_geometria[value_col].isna().sum()),
        crs_salida=GEOJSON_CRS,
        **stats,
    )
    return layer, report