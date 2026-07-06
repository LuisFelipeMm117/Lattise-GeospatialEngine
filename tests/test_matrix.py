# tests/test_matrix.py
"""
Pruebas de spatial.simulation.matrix — SpatialMatrix (Incremento 1, Stage 8 SEE).

Sigue el mismo criterio que tests/test_graph.py:
  1. Fixtures AGEB sintéticas reutilizadas EXACTAMENTE (grid 2x2, grid con isla)
     para construir un `SpatialGraph` real vía `SpatialGraphBuilder` (Spatial
     Graph Builder, cerrado) y persistirlo a `.gal` (+ metadata) con
     `to_graph_files()` / `to_gal()` reales — sin mockear el escritor.
  2. `SpatialMatrix.from_gal()` se ejerce sobre esos archivos genuinos,
     nunca reconstruyendo el grafo en memoria por otra vía.
  3. El parser `load_gal()` se ejerce también de forma aislada contra
     contenido `.gal` escrito a mano, para cubrir los casos de borde de
     formato inválido que `SpatialGraphBuilder` nunca produciría por sí solo.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon

from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.matrix import (
    SpatialMatrix,
    SpatialMatrixReport,
    _build_row_standardized_matrix,
    _validate_row_stochastic,
    load_gal,
)
from spatial.warehouse.ageb_loader import AGEBLoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — idénticas a tests/test_graph.py
# ══════════════════════════════════════════════════════════════════════════
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


def _write_gal_and_metadata(tmp_path, criterio="queen", gdf=None):
    gdf = gdf if gdf is not None else _grid_2x2_gdf()
    gb = SpatialGraphBuilder(criterio=criterio)
    graph = gb.build(gdf)
    gal_path, metadata_path = gb.to_graph_files(
        graph,
        gal_path=tmp_path / "graph.gal",
        metadata_path=tmp_path / "graph_metadata.json",
    )
    return graph, gal_path, metadata_path


# ══════════════════════════════════════════════════════════════════════════
# SpatialMatrix.from_gal — reconstrucción sobre artefactos reales
# ══════════════════════════════════════════════════════════════════════════
def test_from_gal_reconstructs_queen_grid_correctly(tmp_path):
    graph, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")

    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    assert set(sm.ids) == set(graph.neighbors.keys())
    assert sm.id_col == "cvegeo"
    assert sm.criterio == "queen"

    i = sm.index_of("A00")
    fila = sm.row("A00")
    vecinos_esperados = {"A01", "A10", "A11"}
    assert set(sm.neighbors_of("A00")) == vecinos_esperados
    for vecino in vecinos_esperados:
        j = sm.index_of(vecino)
        assert fila[j] == pytest.approx(1 / 3)
    assert fila.sum() == pytest.approx(1.0)


def test_from_gal_rook_matches_graph_neighbors_exactly(tmp_path):
    graph, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="rook")
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    for cvegeo in sm.ids:
        assert set(sm.neighbors_of(cvegeo)) == set(graph.neighbors_of(cvegeo))

    assert set(sm.neighbors_of("A00")) == {"A01", "A10"}
    assert "A11" not in sm.neighbors_of("A00")
    assert sm.criterio == "rook"


def test_from_gal_row_standardization_sums_to_one_for_every_non_island(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    row_sums = sm.W.sum(axis=1)
    assert np.allclose(row_sums, 1.0)
    assert sm.report.filas_no_estocasticas == []


def test_from_gal_island_row_is_entirely_zero(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(
        tmp_path, criterio="queen", gdf=_grid_with_island_gdf()
    )
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    assert sm.is_island("ISLA") is True
    fila_isla = sm.row("ISLA")
    assert fila_isla.sum() == pytest.approx(0.0)
    assert np.all(fila_isla == 0.0)
    assert sm.report.islas == ["ISLA"]
    assert sm.report.n_islas == 1
    assert sm.is_island("A00") is False


def test_from_gal_never_applies_distance_fallback_to_islands(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(
        tmp_path, criterio="rook", gdf=_grid_with_island_gdf()
    )
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    assert sm.neighbors_of("ISLA") == []
    assert sm.row("ISLA").sum() == pytest.approx(0.0)


def test_from_gal_ids_order_matches_gal_file_order(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")
    lines = gal_path.read_text(encoding="utf-8").splitlines()

    orden_en_archivo = []
    i = 1
    while i < len(lines):
        node_id = lines[i].split()[0]
        orden_en_archivo.append(node_id)
        i += 2

    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    assert sm.ids == orden_en_archivo


def test_from_gal_without_metadata_leaves_criterio_none(tmp_path):
    gdf = _grid_2x2_gdf()
    graph = SpatialGraphBuilder(criterio="queen").build(gdf)
    gal_path = tmp_path / "graph.gal"
    graph.to_gal(gal_path)  # solo .gal, sin metadata.json

    sm = SpatialMatrix.from_gal(gal_path, metadata_path=tmp_path / "no_existe.json")

    assert sm.criterio is None
    assert sm.report.criterio is None
    assert sm.report.metadata_encontrada is False
    assert "desconocido" in sm.report.summary().lower()


def test_from_gal_with_metadata_none_skips_metadata_lookup_entirely(tmp_path):
    gdf = _grid_2x2_gdf()
    graph = SpatialGraphBuilder(criterio="queen").build(gdf)
    gal_path = tmp_path / "graph.gal"
    graph.to_gal(gal_path)

    sm = SpatialMatrix.from_gal(gal_path, metadata_path=None)

    assert sm.criterio is None
    assert sm.report.metadata_encontrada is False


def test_from_gal_raises_filenotfound_when_gal_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        SpatialMatrix.from_gal(tmp_path / "no_existe.gal", metadata_path=None)


def test_to_frame_is_labeled_by_cvegeo_and_matches_row(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    df = sm.to_frame()
    assert list(df.index) == sm.ids
    assert list(df.columns) == sm.ids
    assert np.allclose(df.loc["A00"].values, sm.row("A00"))


def test_index_of_and_neighbors_of_raise_keyerror_for_unknown_id(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    with pytest.raises(KeyError):
        sm.index_of("NO_EXISTE")
    with pytest.raises(KeyError):
        sm.neighbors_of("NO_EXISTE")


def test_single_node_graph_is_a_trivial_island_in_matrix(tmp_path):
    raw = gpd.GeoDataFrame({"cvegeo": ["A00"], "geometry": [_square(0, 0)]}, crs="EPSG:4326")
    gdf = AGEBLoader().normalize(raw)
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen", gdf=gdf)

    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    assert sm.W.shape == (1, 1)
    assert sm.is_island("A00") is True
    assert sm.report.n_nodos == 1


# ══════════════════════════════════════════════════════════════════════════
# SpatialMatrixReport — to_dict / to_json / summary
# ══════════════════════════════════════════════════════════════════════════
def test_report_to_dict_and_json_roundtrip(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(
        tmp_path, criterio="queen", gdf=_grid_with_island_gdf()
    )
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)

    report_dict = sm.report.to_dict()
    assert report_dict["n_islas"] == 1
    assert report_dict["islas"] == ["ISLA"]

    out_path = tmp_path / "spatial_matrix_report.json"
    sm.report.to_json(out_path)
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == report_dict


def test_report_summary_mentions_islands_when_present(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(
        tmp_path, criterio="queen", gdf=_grid_with_island_gdf()
    )
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    assert "isla" in sm.report.summary().lower()


def test_report_summary_confirms_no_islands_when_absent(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    assert "sin islas" in sm.report.summary().lower()


def test_report_summary_reports_valid_rows_when_no_violations(tmp_path):
    _, gal_path, metadata_path = _write_gal_and_metadata(tmp_path, criterio="queen")
    sm = SpatialMatrix.from_gal(gal_path, metadata_path)
    assert "todas las filas de w son válidas" in sm.report.summary().lower()


# ══════════════════════════════════════════════════════════════════════════
# load_gal — parser puro, casos de borde de formato escritos a mano
# ══════════════════════════════════════════════════════════════════════════
def test_load_gal_reads_valid_file_written_by_graph(tmp_path):
    _, gal_path, _ = _write_gal_and_metadata(tmp_path, criterio="rook")
    id_col, ids, neighbors = load_gal(gal_path)

    assert id_col == "cvegeo"
    assert set(ids) == {"A00", "A01", "A10", "A11"}
    assert set(neighbors["A00"]) == {"A01", "A10"}


def test_load_gal_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_gal(tmp_path / "no_existe.gal")


def test_load_gal_raises_on_empty_file(tmp_path):
    p = tmp_path / "vacio.gal"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_invalid_header(tmp_path):
    p = tmp_path / "malo.gal"
    p.write_text("encabezado incompleto\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_non_numeric_node_count(tmp_path):
    p = tmp_path / "malo.gal"
    p.write_text("0 dos spatial_graph cvegeo\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_malformed_node_header_line(tmp_path):
    p = tmp_path / "malo.gal"
    p.write_text(
        "0 1 spatial_graph cvegeo\n"
        "A00 0 extra\n"
        "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_non_numeric_degree(tmp_path):
    p = tmp_path / "malo.gal"
    p.write_text(
        "0 1 spatial_graph cvegeo\n"
        "A00 dos\n"
        "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_degree_mismatch(tmp_path):
    p = tmp_path / "malo.gal"
    # Declara grado 2 pero solo lista 1 vecino
    p.write_text(
        "0 2 spatial_graph cvegeo\n"
        "A00 2\n"
        "A01\n"
        "A01 1\n"
        "A00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_truncated_file_missing_neighbor_line(tmp_path):
    p = tmp_path / "malo.gal"
    p.write_text("0 1 spatial_graph cvegeo\nA00 0", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_duplicate_ids(tmp_path):
    p = tmp_path / "malo.gal"
    p.write_text(
        "0 2 spatial_graph cvegeo\n"
        "A00 0\n"
        "\n"
        "A00 0\n"
        "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_declared_count_mismatch(tmp_path):
    p = tmp_path / "malo.gal"
    # Encabezado declara 2 nodos pero solo hay 1
    p.write_text(
        "0 2 spatial_graph cvegeo\n"
        "A00 0\n"
        "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_raises_on_unknown_neighbor_reference(tmp_path):
    p = tmp_path / "malo.gal"
    # A00 declara vecino "FANTASMA" que no existe como nodo del archivo
    p.write_text(
        "0 1 spatial_graph cvegeo\n"
        "A00 1\n"
        "FANTASMA\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gal(p)


def test_load_gal_handles_empty_neighbor_line_for_island(tmp_path):
    p = tmp_path / "isla.gal"
    p.write_text(
        "0 1 spatial_graph cvegeo\n"
        "SOLO 0\n"
        "\n",
        encoding="utf-8",
    )
    id_col, ids, neighbors = load_gal(p)
    assert id_col == "cvegeo"
    assert ids == ["SOLO"]
    assert neighbors["SOLO"] == []


# ══════════════════════════════════════════════════════════════════════════
# Helpers internos — _build_row_standardized_matrix / _validate_row_stochastic
# ══════════════════════════════════════════════════════════════════════════
def test_build_row_standardized_matrix_basic_case():
    ids = ["A", "B", "C"]
    neighbors = {"A": ["B", "C"], "B": ["A"], "C": []}
    W = _build_row_standardized_matrix(ids, neighbors)

    assert W.shape == (3, 3)
    assert W[0, 1] == pytest.approx(0.5)
    assert W[0, 2] == pytest.approx(0.5)
    assert W[1, 0] == pytest.approx(1.0)
    assert np.all(W[2] == 0.0)
    # Diagonal siempre en cero, incluso si un nodo se referenciara a sí mismo
    assert np.all(np.diag(W) == 0.0)


def test_validate_row_stochastic_flags_only_invalid_rows():
    ids = ["A", "B", "C"]
    W_valida = np.array([
        [0.0, 1.0, 0.0],
        [0.5, 0.0, 0.5],
        [0.0, 0.0, 0.0],
    ])
    assert _validate_row_stochastic(W_valida, ids) == []

    W_corrupta = np.array([
        [0.0, 1.0, 0.0],
        [0.3, 0.0, 0.3],   # suma 0.6 — ni isla (0) ni fila-estandarizada (1)
        [0.0, 0.0, 0.0],
    ])
    invalidas = _validate_row_stochastic(W_corrupta, ids)
    assert invalidas == ["B"]