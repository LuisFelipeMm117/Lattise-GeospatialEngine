# tests/test_builder.py
"""
Pruebas de WarehouseBuilder (Stage 5) usando un grid sintético de AGEBs
y establecimientos DENUE sintéticos — mismo patrón que test_ageb_loader.py
y test_denue_loader.py (sin requerir insumos reales de INEGI).

Escenario construido a propósito para ejercitar:
  - Spatial Join vía STRtree: asignados, huérfanos y (en un caso aparte)
    ambiguos.
  - Agregación por (AGEB, sector_serio) con establecimientos y empleo.
  - Exclusión explícita de códigos SCIAN sin mapeo en el crosswalk.
  - Cálculo de ω con método 'empleo' (SEC001, SEC002) y con fallback a
    'establecimientos' (SEC003, donde ningún establecimiento reporta
    personal ocupado reconocido).
  - Reporte de integridad (sumas de ω, duplicados, cobertura).
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import (
    SpatialJoinReport,
    WarehouseBuilder,
    WarehouseIntegrityReport,
)
from spatial.warehouse.denue_loader import DENUELoader

SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]

LON0, LAT0, CELL = -99.20, 19.40, 0.01


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — grid sintético de AGEBs + establecimientos DENUE sintéticos
# ══════════════════════════════════════════════════════════════════════════
def _make_ageb_grid_raw() -> gpd.GeoDataFrame:
    """Grid 2x2 de AGEBs cuadrados de 0.01° cerca de CDMX, en EPSG:4326."""
    cells = {"A00": (0, 0), "A01": (0, 1), "A10": (1, 0), "A11": (1, 1)}
    polys, ids = [], []
    for cvegeo, (i, j) in cells.items():
        x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
        polys.append(Polygon([
            (x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL),
        ]))
        ids.append(cvegeo)
    return gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")


def _make_denue_raw() -> pd.DataFrame:
    """
    8 establecimientos:
      A1, A2 → AGEB A00, scian 111111 (SEC001)
      A3     → AGEB A11, scian 111111 (SEC001)
      A4     → AGEB A01, scian 222222 (SEC002)
      A5     → AGEB A00, scian 333333 (SEC003), personal ocupado desconocido
      A6     → AGEB A10, scian 333333 (SEC003), personal ocupado desconocido
      A7     → AGEB A00, scian 999999 (SIN mapeo en el crosswalk)
      A8     → fuera del grid (huérfano), scian 111111 (SEC001)
    """
    rows = [
        ("A1", "111111", LON0 + 0.003, LAT0 + 0.003, "0 a 5 personas"),
        ("A2", "111111", LON0 + 0.004, LAT0 + 0.004, "6 a 10 personas"),
        ("A3", "111111", LON0 + 0.013, LAT0 + 0.013, "11 a 30 personas"),
        ("A4", "222222", LON0 + 0.003, LAT0 + 0.013, "0 a 5 personas"),
        ("A5", "333333", LON0 + 0.002, LAT0 + 0.001, "rango_desconocido"),
        ("A6", "333333", LON0 + 0.013, LAT0 + 0.003, "rango_desconocido"),
        ("A7", "999999", LON0 + 0.001, LAT0 + 0.002, "0 a 5 personas"),
        ("A8", "111111", LON0 - 0.30, LAT0 - 0.30,  "0 a 5 personas"),
    ]
    return pd.DataFrame(
        rows, columns=["id", "codigo_act", "longitud", "latitud", "per_ocu"]
    ).assign(nom_estab=lambda d: "Estab " + d["id"])


@pytest.fixture
def ageb_gdf() -> gpd.GeoDataFrame:
    return AGEBLoader().normalize(_make_ageb_grid_raw())


@pytest.fixture
def denue_gdf_no_sector() -> gpd.GeoDataFrame:
    return DENUELoader().normalize(_make_denue_raw())


@pytest.fixture
def wb() -> WarehouseBuilder:
    return WarehouseBuilder(serio_sectors=SERIO_SECTORS)


def _crosswalk_table() -> pd.DataFrame:
    return pd.DataFrame({
        "scian_codigo": ["111111", "222222", "333333"],
        "sector_serio": ["SEC001", "SEC002", "SEC003"],
        "notas": ["", "", ""],
    })


@pytest.fixture
def denue_gdf(wb, denue_gdf_no_sector) -> gpd.GeoDataFrame:
    """DENUE normalizado + sector_serio aplicado vía CrosswalkBuilder (sin descartar A7)."""
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, unmapped = wb.crosswalk_builder.apply(denue_gdf_no_sector, lookup, scian_col="scian")
    assert unmapped == ["999999"]  # A7 queda sin sector, tal como se diseñó el fixture
    return mapped


# ══════════════════════════════════════════════════════════════════════════
# spatial_join()
# ══════════════════════════════════════════════════════════════════════════
def test_spatial_join_matches_orphans_and_reports(wb, ageb_gdf, denue_gdf):
    joined, report = wb.spatial_join(ageb_gdf, denue_gdf)

    assert isinstance(report, SpatialJoinReport)
    assert report.n_total == 8
    assert report.n_matched == 7          # A1..A7
    assert report.n_orphan == 1           # A8
    assert report.n_ambiguous == 0
    assert "A8" in report.orphan_ids

    assert len(joined) == 8               # ningún registro se descarta
    assert set(joined.loc[joined["_join_status"] == "matched", "cvegeo"]) == {"A00", "A01", "A10", "A11"}
    orphan_row = joined[joined["id"] == "A8"].iloc[0]
    assert pd.isna(orphan_row["cvegeo"])


def test_spatial_join_flags_ambiguous_on_shared_boundary(wb, ageb_gdf):
    # Punto tomado del vértice exacto compartido por A00 y A10 (ya
    # reproyectado). Se usa el vértice — no el punto medio de la arista —
    # porque GEOS evalúa `covered_by` con precisión finita: un punto medio
    # reconstruido de forma independiente puede quedar a ~1e-12 unidades del
    # borde real y no clasificar como "cubierto". El vértice, en cambio, es
    # el mismo float exacto en ambos polígonos (proviene de la misma
    # reproyección), por lo que el empate es determinístico.
    from shapely.geometry import Point

    a00_geom = ageb_gdf.loc[ageb_gdf["cvegeo"] == "A00", "geometry"].iloc[0]
    shared_vertex = Point(list(a00_geom.exterior.coords)[1])  # esquina (x0+CELL, y0)

    boundary_denue = gpd.GeoDataFrame(
        {"id": ["B1"], "scian": ["111111"], "empleo_estimado": [2.5]},
        geometry=[shared_vertex], crs=ageb_gdf.crs,
    )
    joined, report = wb.spatial_join(ageb_gdf, boundary_denue)

    assert report.n_ambiguous == 1
    assert "B1" in report.ambiguous_ids
    assert joined.iloc[0]["_join_status"] == "ambiguous"


def test_spatial_join_raises_on_crs_mismatch(wb, ageb_gdf, denue_gdf):
    denue_wrong_crs = denue_gdf.to_crs(epsg=4326)
    with pytest.raises(ValueError):
        wb.spatial_join(ageb_gdf, denue_wrong_crs)


def test_spatial_join_raises_on_duplicate_ageb_ids(wb, ageb_gdf, denue_gdf):
    dup_ageb = pd.concat([ageb_gdf, ageb_gdf.iloc[[0]]], ignore_index=True)
    dup_ageb = gpd.GeoDataFrame(dup_ageb, geometry="geometry", crs=ageb_gdf.crs)
    with pytest.raises(ValueError):
        wb.spatial_join(dup_ageb, denue_gdf)


# ══════════════════════════════════════════════════════════════════════════
# aggregate()
# ══════════════════════════════════════════════════════════════════════════
def test_aggregate_groups_by_ageb_and_sector_excluding_unmapped_and_orphans(wb, ageb_gdf, denue_gdf):
    joined, _ = wb.spatial_join(ageb_gdf, denue_gdf)
    agg = wb.aggregate(joined, ageb_gdf)

    # 5 pares (AGEB, sector): (A00,SEC001) (A11,SEC001) (A01,SEC002) (A00,SEC003) (A10,SEC003)
    assert len(agg) == 5
    assert set(zip(agg["cvegeo"], agg["sector_serio"])) == {
        ("A00", "SEC001"), ("A11", "SEC001"), ("A01", "SEC002"),
        ("A00", "SEC003"), ("A10", "SEC003"),
    }

    row_a00_sec001 = agg[(agg["cvegeo"] == "A00") & (agg["sector_serio"] == "SEC001")].iloc[0]
    assert row_a00_sec001["n_establecimientos"] == 2         # A1 + A2
    assert row_a00_sec001["empleo_total"] == pytest.approx(2.5 + 8.0)
    assert row_a00_sec001["n_empleo_faltante"] == 0

    row_a00_sec003 = agg[(agg["cvegeo"] == "A00") & (agg["sector_serio"] == "SEC003")].iloc[0]
    assert row_a00_sec003["n_establecimientos"] == 1          # A5
    assert row_a00_sec003["empleo_total"] == 0.0               # sin datos de empleo → 0 explícito
    assert row_a00_sec003["n_empleo_faltante"] == 1

    # scian 999999 (A7) y huérfano (A8) no generan ningún par
    assert not ((agg["cvegeo"] == "A10") & (agg["sector_serio"] == "SEC001")).any()
    assert isinstance(agg, gpd.GeoDataFrame)
    assert agg.crs == ageb_gdf.crs


def test_aggregate_requires_spatial_join_first(wb, ageb_gdf, denue_gdf):
    with pytest.raises(ValueError):
        wb.aggregate(denue_gdf, ageb_gdf)  # falta _join_status


def test_aggregate_requires_sector_col(wb, ageb_gdf, denue_gdf_no_sector):
    joined, _ = wb.spatial_join(ageb_gdf, denue_gdf_no_sector)
    with pytest.raises(ValueError):
        wb.aggregate(joined, ageb_gdf)  # falta sector_serio (crosswalk no aplicado)


# ══════════════════════════════════════════════════════════════════════════
# compute_weights()
# ══════════════════════════════════════════════════════════════════════════
def test_compute_weights_uses_employment_when_available(wb, ageb_gdf, denue_gdf):
    joined, _ = wb.spatial_join(ageb_gdf, denue_gdf)
    agg = wb.aggregate(joined, ageb_gdf)
    weighted = wb.compute_weights(agg)

    sec001 = weighted[weighted["sector_serio"] == "SEC001"]
    assert set(sec001["omega_metodo"]) == {"empleo"}
    assert sec001["omega"].sum() == pytest.approx(1.0)

    a00 = sec001[sec001["cvegeo"] == "A00"].iloc[0]
    a11 = sec001[sec001["cvegeo"] == "A11"].iloc[0]
    assert a00["omega"] == pytest.approx(10.5 / 31.0)
    assert a11["omega"] == pytest.approx(20.5 / 31.0)


def test_compute_weights_falls_back_to_establishments_when_no_employment_data(wb, ageb_gdf, denue_gdf):
    joined, _ = wb.spatial_join(ageb_gdf, denue_gdf)
    agg = wb.aggregate(joined, ageb_gdf)
    weighted = wb.compute_weights(agg)

    sec003 = weighted[weighted["sector_serio"] == "SEC003"]
    assert set(sec003["omega_metodo"]) == {"establecimientos"}
    assert sec003["omega"].sum() == pytest.approx(1.0)
    assert sec003["omega"].tolist() == pytest.approx([0.5, 0.5])


def test_compute_weights_on_empty_aggregate_returns_empty_columns(wb, ageb_gdf):
    empty_agg = gpd.GeoDataFrame(
        {"cvegeo": [], "sector_serio": [], "n_establecimientos": [], "empleo_total": [], "n_empleo_faltante": []},
        geometry=gpd.GeoSeries([], crs=ageb_gdf.crs),
    )
    weighted = wb.compute_weights(empty_agg)
    assert "omega" in weighted.columns
    assert "omega_metodo" in weighted.columns
    assert len(weighted) == 0


# ══════════════════════════════════════════════════════════════════════════
# validate_integrity()
# ══════════════════════════════════════════════════════════════════════════
def test_validate_integrity_passes_on_well_formed_warehouse(wb, ageb_gdf, denue_gdf):
    joined, join_report = wb.spatial_join(ageb_gdf, denue_gdf)
    agg = wb.aggregate(joined, ageb_gdf)
    weighted = wb.compute_weights(agg)
    report = wb.validate_integrity(weighted, join_report)

    assert isinstance(report, WarehouseIntegrityReport)
    assert report.n_ageb_sector_pairs == 5
    assert report.n_invalid == 0
    assert report.sectors_omega_not_summing_to_one == []
    assert report.coverage_establecimientos == pytest.approx(6 / 8)   # 6 de 8 estab. terminan en el warehouse
    assert report.coverage_empleo == pytest.approx(1 - 2 / 6)          # 2 de 6 sin empleo conocido


def test_validate_integrity_flags_duplicate_pairs(wb, ageb_gdf, denue_gdf):
    joined, join_report = wb.spatial_join(ageb_gdf, denue_gdf)
    agg = wb.aggregate(joined, ageb_gdf)
    weighted = wb.compute_weights(agg)

    dup = pd.concat([weighted, weighted.iloc[[0]]], ignore_index=True)
    dup = gpd.GeoDataFrame(dup, geometry="geometry", crs=weighted.crs)

    report = wb.validate_integrity(dup, join_report)
    assert report.checks["chk_no_duplicate_pairs"] >= 2
    assert report.n_invalid >= 2


def test_validate_integrity_on_empty_warehouse(wb):
    empty = gpd.GeoDataFrame(
        {"cvegeo": [], "sector_serio": [], "n_establecimientos": [], "empleo_total": [],
         "n_empleo_faltante": [], "omega": [], "omega_metodo": []},
        geometry=gpd.GeoSeries([], crs="EPSG:6372"),
    )
    report = wb.validate_integrity(empty, SpatialJoinReport(n_total=0))
    assert report.n_ageb_sector_pairs == 0
    assert report.n_valid == 0
    assert report.n_invalid == 0


# ══════════════════════════════════════════════════════════════════════════
# build_from_gdfs() / build() — orquestación completa
# ══════════════════════════════════════════════════════════════════════════
def test_build_from_gdfs_returns_geodataframe_and_stores_reports(wb, ageb_gdf, denue_gdf):
    warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)

    assert isinstance(warehouse, gpd.GeoDataFrame)
    assert len(warehouse) == 5
    assert {"cvegeo", "sector_serio", "n_establecimientos", "empleo_total", "omega", "omega_metodo"} <= set(warehouse.columns)
    assert warehouse.crs.to_epsg() == wb.epsg_target

    assert wb.join_report is not None and wb.join_report.n_total == 8
    assert wb.integrity_report is not None and wb.integrity_report.n_invalid == 0


def test_build_from_gdfs_requires_sector_col(wb, ageb_gdf, denue_gdf_no_sector):
    with pytest.raises(ValueError):
        wb.build_from_gdfs(ageb_gdf, denue_gdf_no_sector)


def test_apply_crosswalk_requires_serio_sectors():
    wb_no_sectors = WarehouseBuilder()  # sin serio_sectors
    with pytest.raises(ValueError):
        wb_no_sectors.apply_crosswalk(pd.DataFrame({"scian": ["111111"]}), "no_existe.csv")


def test_build_end_to_end_from_files(tmp_path, wb):
    ageb_path = tmp_path / "ageb_grid.geojson"
    _make_ageb_grid_raw().to_file(ageb_path, driver="GeoJSON")

    denue_path = tmp_path / "denue.csv"
    _make_denue_raw().to_csv(denue_path, index=False, encoding="utf-8")

    crosswalk_path = tmp_path / "crosswalk.csv"
    _crosswalk_table().to_csv(crosswalk_path, index=False)

    warehouse = wb.build(ageb_path, denue_path, crosswalk_path)

    assert isinstance(warehouse, gpd.GeoDataFrame)
    assert len(warehouse) == 5
    assert wb.join_report.n_total == 8
    assert wb.integrity_report.n_invalid == 0


def test_to_warehouse_files_serializes_parquet_and_metadata(tmp_path, wb, ageb_gdf, denue_gdf):
    warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)
    parquet_path, metadata_path = wb.to_warehouse_files(
        warehouse,
        parquet_path=tmp_path / "warehouse.parquet",
        metadata_path=tmp_path / "metadata.json",
    )

    assert parquet_path.exists()
    assert metadata_path.exists()

    reloaded = gpd.read_parquet(parquet_path)
    assert len(reloaded) == len(warehouse)

    import json
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["n_rows"] == len(warehouse)
    assert set(metadata["sectors"]) == {"SEC001", "SEC002", "SEC003"}
    assert metadata["join_report"]["n_total"] == 8
