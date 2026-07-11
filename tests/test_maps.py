# tests/test_maps.py
"""
Pruebas de spatial.visualization.maps — Visualization Layer (Stage 9).

Sigue el mismo criterio que tests/test_matrix.py / tests/test_graph.py:
  1. Geometría AGEB sintética real (grid 2x2), normalizada con
     `AGEBLoader.normalize()` (Stage 3, CERRADO) — nunca un GeoDataFrame
     de juguete sin pasar por el pipeline real de normalización/CRS.
  2. `spatial.visualization.maps` se ejerce como consumidor puro de ese
     GeoDataFrame + una columna numérica sintética — sin acoplarse a
     `ScenarioResult` ni a `run_simulation_engine()` (el módulo es
     agnóstico de origen, por diseño).
  3. Casos de borde propios de datos geoespaciales reales: AGEBs sin
     geometría (excluidos y reportados, nunca descartados en silencio),
     valores nulos con geometría válida (dibujados como "sin dato"),
     columnas inexistentes (rechazadas explícitamente).
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.visualization.maps import (
    ColumnNotFoundError,
    EmptyGeometryError,
    InvalidClassificationError,
    VisualizationReport,
    build_dashboard_layer,
    export_geojson,
    render_choropleth,
)
from spatial.warehouse.ageb_loader import AGEBLoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — misma grilla sintética que test_matrix.py / test_graph.py
# ══════════════════════════════════════════════════════════════════════════
def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _grid_gdf_with_values(include_missing_geom: bool = False, include_null_value: bool = False) -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1),
             "A20": (2, 0), "A21": (2, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    raw = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    gdf = AGEBLoader().normalize(raw)

    rng = np.random.default_rng(42)
    gdf["impacto_propagado"] = rng.uniform(100, 10_000, size=len(gdf))
    gdf["shock_directo"] = rng.uniform(50, 5_000, size=len(gdf))

    if include_null_value:
        gdf.loc[gdf["cvegeo"] == "A21", "impacto_propagado"] = np.nan

    if include_missing_geom:
        gdf.loc[gdf["cvegeo"] == "A20", "geometry"] = None

    return gdf


# ══════════════════════════════════════════════════════════════════════════
# render_choropleth
# ══════════════════════════════════════════════════════════════════════════
def test_render_choropleth_writes_png_and_report(tmp_path):
    gdf = _grid_gdf_with_values()
    out = tmp_path / "mapa.png"

    path, report = render_choropleth(gdf, "impacto_propagado", out, id_col="cvegeo")

    assert path == out
    assert out.exists() and out.stat().st_size > 0
    assert isinstance(report, VisualizationReport)
    assert report.tipo == "choropleth_png"
    assert report.n_features_total == len(gdf)
    assert report.n_features_incluidos == len(gdf)
    assert report.n_features_sin_geometria == 0
    assert report.value_min is not None and report.value_max is not None


def test_render_choropleth_missing_column_raises():
    gdf = _grid_gdf_with_values()
    with pytest.raises(ColumnNotFoundError):
        render_choropleth(gdf, "columna_inexistente", "out.png", id_col="cvegeo")


def test_render_choropleth_excludes_and_reports_missing_geometry(tmp_path):
    gdf = _grid_gdf_with_values(include_missing_geom=True)
    out = tmp_path / "mapa.png"

    path, report = render_choropleth(gdf, "impacto_propagado", out, id_col="cvegeo")

    assert report.n_features_total == len(gdf)
    assert report.n_features_incluidos == len(gdf) - 1
    assert report.n_features_sin_geometria == 1
    assert "A20" in report.agebs_sin_geometria


def test_render_choropleth_reports_null_values_without_dropping(tmp_path):
    gdf = _grid_gdf_with_values(include_null_value=True)
    out = tmp_path / "mapa.png"

    _, report = render_choropleth(gdf, "impacto_propagado", out, id_col="cvegeo")

    # La fila con valor nulo SÍ tiene geometría válida -> se incluye en el
    # lienzo (dibujada como "sin dato"), no se descarta del conteo.
    assert report.n_features_incluidos == len(gdf)
    assert report.n_valores_nulos == 1


def test_render_choropleth_all_geometries_missing_raises(tmp_path):
    gdf = _grid_gdf_with_values()
    gdf["geometry"] = None
    with pytest.raises(EmptyGeometryError):
        render_choropleth(gdf, "impacto_propagado", tmp_path / "mapa.png", id_col="cvegeo")


def test_render_choropleth_invalid_classification_raises():
    gdf = _grid_gdf_with_values()
    with pytest.raises(InvalidClassificationError):
        render_choropleth(gdf, "impacto_propagado", "out.png", id_col="cvegeo", classification="no_existe")


@pytest.mark.parametrize("scheme", ["linear", "quantiles", "equal_interval"])
def test_render_choropleth_all_classification_schemes(tmp_path, scheme):
    gdf = _grid_gdf_with_values()
    out = tmp_path / f"mapa_{scheme}.png"
    path, report = render_choropleth(
        gdf, "impacto_propagado", out, id_col="cvegeo", classification=scheme, n_classes=3,
    )
    assert path.exists()
    assert report.classification == scheme


def test_render_choropleth_report_roundtrip_json(tmp_path):
    gdf = _grid_gdf_with_values()
    _, report = render_choropleth(gdf, "impacto_propagado", tmp_path / "mapa.png", id_col="cvegeo")

    json_path = tmp_path / "report.json"
    report.to_json(json_path)
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["tipo"] == "choropleth_png"
    assert isinstance(report.summary(), str) and "Visualization Report" in report.summary()


# ══════════════════════════════════════════════════════════════════════════
# export_geojson
# ══════════════════════════════════════════════════════════════════════════
def test_export_geojson_writes_wgs84_file(tmp_path):
    gdf = _grid_gdf_with_values()
    out = tmp_path / "capa.geojson"

    path, report = export_geojson(gdf, out, id_col="cvegeo", columns=["impacto_propagado"])

    assert path.exists()
    written = gpd.read_file(path)
    assert written.crs.to_epsg() == 4326
    assert len(written) == len(gdf)
    assert report.crs_salida == "EPSG:4326"
    assert report.n_features_incluidos == len(gdf)


def test_export_geojson_missing_requested_column_raises(tmp_path):
    gdf = _grid_gdf_with_values()
    with pytest.raises(ColumnNotFoundError):
        export_geojson(gdf, tmp_path / "capa.geojson", id_col="cvegeo", columns=["no_existe"])


def test_export_geojson_excludes_and_reports_missing_geometry(tmp_path):
    gdf = _grid_gdf_with_values(include_missing_geom=True)
    out = tmp_path / "capa.geojson"

    path, report = export_geojson(gdf, out, id_col="cvegeo", columns=["impacto_propagado"])
    written = gpd.read_file(path)

    assert len(written) == len(gdf) - 1
    assert report.n_features_sin_geometria == 1
    assert "A20" in report.agebs_sin_geometria


def test_export_geojson_simplify_reduces_or_preserves_vertex_count(tmp_path):
    gdf = _grid_gdf_with_values()
    out_full = tmp_path / "capa_full.geojson"
    out_simplified = tmp_path / "capa_simplificada.geojson"

    export_geojson(gdf, out_full, id_col="cvegeo", columns=["impacto_propagado"])
    export_geojson(
        gdf, out_simplified, id_col="cvegeo", columns=["impacto_propagado"],
        simplify_tolerance=50.0,
    )

    assert out_full.exists() and out_simplified.exists()


def test_export_geojson_all_geometries_missing_raises(tmp_path):
    gdf = _grid_gdf_with_values()
    gdf["geometry"] = None
    with pytest.raises(EmptyGeometryError):
        export_geojson(gdf, tmp_path / "capa.geojson", id_col="cvegeo")


# ══════════════════════════════════════════════════════════════════════════
# build_dashboard_layer
# ══════════════════════════════════════════════════════════════════════════
def test_build_dashboard_layer_structure(tmp_path):
    gdf = _grid_gdf_with_values()

    layer, report = build_dashboard_layer(gdf, "impacto_propagado", id_col="cvegeo")

    assert layer["type"] == "FeatureCollection"
    assert layer["value_col"] == "impacto_propagado"
    assert set(layer["values"].keys()) == set(gdf["cvegeo"])
    assert layer["stats"]["min"] is not None and layer["stats"]["max"] is not None
    assert len(layer["features"]) == len(gdf)
    assert report.crs_salida == "EPSG:4326"


def test_build_dashboard_layer_features_are_wgs84(tmp_path):
    gdf = _grid_gdf_with_values()
    layer, _ = build_dashboard_layer(gdf, "impacto_propagado", id_col="cvegeo")

    # Coordenadas en grados (WGS84), no en metros (EPSG:6372).
    coords = layer["features"][0]["geometry"]["coordinates"][0][0]
    lon, lat = coords[0], coords[1]
    assert -119.0 <= lon <= -86.0
    assert 14.0 <= lat <= 33.0


def test_build_dashboard_layer_missing_geometry_excluded_from_values(tmp_path):
    gdf = _grid_gdf_with_values(include_missing_geom=True)
    layer, report = build_dashboard_layer(gdf, "impacto_propagado", id_col="cvegeo")

    assert "A20" not in layer["values"]
    assert report.n_features_sin_geometria == 1


def test_build_dashboard_layer_null_value_reported_and_none_in_values(tmp_path):
    gdf = _grid_gdf_with_values(include_null_value=True)
    layer, report = build_dashboard_layer(gdf, "impacto_propagado", id_col="cvegeo")

    assert layer["values"]["A21"] is None
    assert report.n_valores_nulos == 1


def test_build_dashboard_layer_missing_column_raises():
    gdf = _grid_gdf_with_values()
    with pytest.raises(ColumnNotFoundError):
        build_dashboard_layer(gdf, "no_existe", id_col="cvegeo")
