from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from spatial.graph.network import (
    GraphReport,
    SpatialGraph,
    SpatialGraphBuilder,
    load_graph_metadata,
)
from spatial.warehouse.ageb_loader import AGEBLoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01


def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _grid_2x2_gdf() -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    raw = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    return AGEBLoader().normalize(raw)


def _grid_with_island_gdf() -> gpd.GeoDataFrame:
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    polys.append(_square(500, 500))
    ids.append("ISLA")
    raw = gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")
    return AGEBLoader().normalize(raw)


def test_build_raises_without_id_col():
    gdf = _grid_2x2_gdf().rename(columns={"cvegeo": "otra_col"})
    gb = SpatialGraphBuilder()
    with pytest.raises(ValueError):
        gb.build(gdf)


def test_build_raises_on_duplicate_ids():
    gdf = _grid_2x2_gdf().copy()
    gdf.loc[1, "cvegeo"] = gdf.loc[0, "cvegeo"]
    gb = SpatialGraphBuilder()
    with pytest.raises(ValueError):
        gb.build(gdf)


def test_build_raises_on_null_geometry():
    gdf = _grid_2x2_gdf().copy()
    gdf.loc[0, "geometry"] = None
    gb = SpatialGraphBuilder()
    with pytest.raises(ValueError):
        gb.build(gdf)


def test_init_raises_on_invalid_criterio():
    with pytest.raises(ValueError):
        SpatialGraphBuilder(criterio="bishop")


def test_queen_contiguity_includes_diagonal_neighbors():
    gdf = _grid_2x2_gdf()
    graph = SpatialGraphBuilder(criterio="queen").build(gdf)

    assert set(graph.neighbors_of("A00")) == {"A01", "A10", "A11"}
    assert graph.report.n_nodos == 4
    assert graph.report.n_aristas == 6
    assert graph.report.grado_min == graph.report.grado_max == 3
    assert graph.report.islas == []


def test_rook_contiguity_excludes_diagonal_neighbors():
    gdf = _grid_2x2_gdf()
    graph = SpatialGraphBuilder(criterio="rook").build(gdf)

    assert set(graph.neighbors_of("A00")) == {"A01", "A10"}
    assert "A11" not in graph.neighbors_of("A00")
    assert graph.report.n_nodos == 4
    assert graph.report.n_aristas == 4
    assert graph.report.grado_min == graph.report.grado_max == 2
    assert graph.report.islas == []


def test_graph_is_undirected():
    gdf = _grid_2x2_gdf()
    graph = SpatialGraphBuilder(criterio="rook").build(gdf)
    for a in graph.neighbors:
        for b in graph.neighbors[a]:
            assert a in graph.neighbors[b], f"{a}->{b} sin arista simétrica {b}->{a}"


def test_neighbors_of_raises_for_unknown_id():
    graph = SpatialGraphBuilder().build(_grid_2x2_gdf())
    with pytest.raises(KeyError):
        graph.neighbors_of("NO_EXISTE")


def test_island_reported_explicitly_and_gets_empty_neighbor_list():
    gdf = _grid_with_island_gdf()
    graph = SpatialGraphBuilder(criterio="queen").build(gdf)

    assert graph.neighbors_of("ISLA") == []
    assert graph.is_island("ISLA") is True
    assert graph.report.islas == ["ISLA"]
    assert graph.report.n_islas == 1
    assert set(graph.neighbors_of("A00")) == {"A01", "A10", "A11"}
    assert graph.is_island("A00") is False


def test_no_distance_fallback_is_ever_applied_to_islands():
    gdf = _grid_with_island_gdf()
    graph_queen = SpatialGraphBuilder(criterio="queen").build(gdf)
    graph_rook = SpatialGraphBuilder(criterio="rook").build(gdf)

    assert graph_queen.neighbors_of("ISLA") == []
    assert graph_rook.neighbors_of("ISLA") == []


def test_single_node_graph_is_a_trivial_island():
    raw = gpd.GeoDataFrame({"cvegeo": ["A00"], "geometry": [_square(0, 0)]}, crs="EPSG:4326")
    gdf = AGEBLoader().normalize(raw)
    graph = SpatialGraphBuilder().build(gdf)

    assert graph.report.n_nodos == 1
    assert graph.report.n_aristas == 0
    assert graph.report.islas == ["A00"]


def test_graph_report_to_dict_and_json(tmp_path):
    graph = SpatialGraphBuilder(criterio="queen").build(_grid_with_island_gdf())
    report_dict = graph.report.to_dict()
    assert report_dict["n_islas"] == 1
    assert report_dict["islas"] == ["ISLA"]

    out_path = tmp_path / "graph_report.json"
    graph.report.to_json(out_path)
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == report_dict


def test_graph_report_summary_mentions_islands_when_present():
    graph = SpatialGraphBuilder().build(_grid_with_island_gdf())
    assert "isla" in graph.report.summary().lower()


def test_graph_report_summary_confirms_no_islands_when_absent():
    graph = SpatialGraphBuilder().build(_grid_2x2_gdf())
    assert "sin islas" in graph.report.summary().lower()


def test_to_gal_writes_expected_format(tmp_path):
    gdf = _grid_2x2_gdf()
    gb = SpatialGraphBuilder(criterio="rook")
    graph = gb.build(gdf)

    gal_path = tmp_path / "graph.gal"
    graph.to_gal(gal_path)

    lines = gal_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "0 4 spatial_graph cvegeo"
    assert len(lines) == 1 + 4 * 2

    parsed = {}
    i = 1
    while i < len(lines):
        node_id, k = lines[i].split()
        vecinos = lines[i + 1].split() if int(k) > 0 else []
        parsed[node_id] = vecinos
        i += 2
    assert set(parsed["A00"]) == {"A01", "A10"}


def test_to_gal_writes_empty_neighbor_line_for_islands(tmp_path):
    graph = SpatialGraphBuilder(criterio="queen").build(_grid_with_island_gdf())
    gal_path = tmp_path / "graph.gal"
    graph.to_gal(gal_path)

    lines = gal_path.read_text(encoding="utf-8").splitlines()
    idx = lines.index("ISLA 0")
    assert lines[idx + 1] == ""


def test_to_graph_files_writes_gal_and_metadata(tmp_path):
    gdf = _grid_with_island_gdf()
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(gdf)

    gal_path, metadata_path = gb.to_graph_files(
        graph,
        gal_path=tmp_path / "graph.gal",
        metadata_path=tmp_path / "graph_metadata.json",
    )

    assert gal_path.exists()
    assert metadata_path.exists()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["criterio"] == "queen"
    assert metadata["id_col"] == "cvegeo"
    assert metadata["report"]["islas"] == ["ISLA"]
    assert metadata["report"]["n_nodos"] == 5


def test_load_graph_metadata_reads_serialized_report(tmp_path):
    gdf = _grid_2x2_gdf()
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(gdf)
    _, metadata_path = gb.to_graph_files(
        graph,
        gal_path=tmp_path / "graph.gal",
        metadata_path=tmp_path / "graph_metadata.json",
    )

    loaded = load_graph_metadata(metadata_path)
    assert loaded["report"]["n_nodos"] == 4
    assert loaded["report"]["islas"] == []


def test_load_graph_metadata_raises_without_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_graph_metadata(tmp_path / "no_existe.json")