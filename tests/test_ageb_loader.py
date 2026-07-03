# tests/test_ageb_loader.py
"""
Pruebas de AGEBLoader usando un grid sintético de polígonos — mismo patrón
que el MVP del Spatial Simulation Engine (Lattise). No requiere shapefiles
reales de INEGI para validar la lógica del pipeline.
"""
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon, GeometryCollection

from spatial.warehouse.ageb_loader import AGEBLoader, VALID_GEOM_TYPES


def _make_grid(n_side: int = 3, cell_size: float = 1.0) -> gpd.GeoDataFrame:
    """Genera un grid n_side x n_side de celdas cuadradas en EPSG:4326."""
    polys, ids = [], []
    for i in range(n_side):
        for j in range(n_side):
            x0, y0 = i * cell_size, j * cell_size
            polys.append(Polygon([
                (x0, y0), (x0 + cell_size, y0),
                (x0 + cell_size, y0 + cell_size), (x0, y0 + cell_size),
            ]))
            ids.append(f"AGEB_{i:02d}{j:02d}")
    gdf = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    return gdf


@pytest.fixture
def clean_grid():
    return _make_grid(n_side=3)


@pytest.fixture
def loader():
    return AGEBLoader()


def test_validate_all_pass_on_clean_grid(loader, clean_grid):
    validated, report = loader.validate(clean_grid)
    assert report.n_total == 9
    assert report.n_valid == 9
    assert report.n_invalid == 0
    assert all(n_fail == 0 for n_fail in report.checks.values())


def test_validate_flags_null_geometry_without_dropping(loader, clean_grid):
    gdf = clean_grid.copy()
    gdf.loc[0, "geometry"] = None
    validated, report = loader.validate(gdf)

    # No se elimina ninguna fila durante validate()
    assert len(validated) == len(gdf) == 9
    assert report.n_invalid == 1
    assert report.checks["chk_geom_not_null"] == 1
    assert validated.loc[0, "_valid_geometry"] == False  # noqa: E712


def test_validate_flags_duplicate_ids(loader, clean_grid):
    gdf = clean_grid.copy()
    gdf.loc[1, "cvegeo"] = gdf.loc[0, "cvegeo"]  # duplicar id
    _, report = loader.validate(gdf)
    assert report.checks["chk_id_unique"] == 2  # ambas filas duplicadas se marcan
    assert set(report.invalid_ids) == {gdf.loc[0, "cvegeo"]}


def test_validate_flags_invalid_geometry_type(loader, clean_grid):
    gdf = clean_grid.copy()
    # GeometryCollection no está en VALID_GEOM_TYPES
    gdf.loc[2, "geometry"] = GeometryCollection([gdf.loc[2, "geometry"], gdf.loc[3, "geometry"]])
    _, report = loader.validate(gdf)
    assert report.checks["chk_geom_type_ok"] >= 1


def test_filter_valid_requires_validate_first(loader, clean_grid):
    with pytest.raises(ValueError):
        loader.filter_valid(clean_grid)  # sin columna _valid_geometry


def test_filter_valid_drops_only_flagged_rows(loader, clean_grid):
    gdf = clean_grid.copy()
    gdf.loc[0, "geometry"] = None
    validated, _ = loader.validate(gdf)
    filtered = loader.filter_valid(validated)
    assert len(filtered) == 8
    assert "AGEB_0000" not in filtered["cvegeo"].values


def test_normalize_reprojects_and_adds_metrics(loader, clean_grid):
    normalized = loader.normalize(clean_grid)
    assert normalized.crs.to_epsg() == loader.epsg_target
    for col in ("area_m2", "perimeter_m", "centroid_lon", "centroid_lat"):
        assert col in normalized.columns
    assert (normalized["area_m2"] > 0).all()
    # columnas en minúsculas
    assert all(c == c.lower() for c in normalized.columns)


def test_normalize_raises_without_crs(loader):
    gdf = _make_grid(n_side=2)
    gdf.crs = None
    with pytest.raises(ValueError):
        loader.normalize(gdf)


def test_full_pipeline_run(tmp_path, loader, clean_grid, monkeypatch):
    src = tmp_path / "ageb_test.geojson"
    clean_grid.to_file(src, driver="GeoJSON")

    # Redirigir directorios de salida a tmp_path para no ensuciar el repo
    import spatial.warehouse.ageb_loader as mod
    monkeypatch.setattr(mod, "VALIDATED_DIR", tmp_path / "validated")
    monkeypatch.setattr(mod, "NORMALIZED_DIR", tmp_path / "normalized")

    result = loader.run(src, drop_invalid=False)
    assert result["report"].n_valid == 9
    assert result["normalized"].crs.to_epsg() == loader.epsg_target
    assert (tmp_path / "normalized").exists()
