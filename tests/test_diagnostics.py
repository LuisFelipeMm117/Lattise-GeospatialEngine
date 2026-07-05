# tests/test_diagnostics.py
"""
Pruebas de Diagnostics (Stage 6) — reutiliza EXACTAMENTE el mismo grid
sintético de AGEBs/DENUE que tests/test_builder.py, para que los números
esperados (n_total=8, n_matched=7, n_orphan=1, 5 pares en el warehouse,
coverage_establecimientos=6/8, coverage_empleo=1-2/6) sean los mismos ya
verificados en Stage 5. Este módulo NO ejerce spatial_join/aggregate/
compute_weights por su cuenta — solo consume warehouse.parquet +
metadata.json ya serializados por WarehouseBuilder.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.analytics.diagnostics import (
    QualityReport,
    compute_quality_report,
    generate_quality_report,
    load_metadata,
    load_warehouse,
    resolve_reports,
)
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]
LON0, LAT0, CELL = -99.20, 19.40, 0.01


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — mismo escenario que tests/test_builder.py
# ══════════════════════════════════════════════════════════════════════════
def _make_ageb_grid_raw() -> gpd.GeoDataFrame:
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
    rows = [
        ("A1", "111111", LON0 + 0.003, LAT0 + 0.003, "0 a 5 personas"),
        ("A2", "111111", LON0 + 0.004, LAT0 + 0.004, "6 a 10 personas"),
        ("A3", "111111", LON0 + 0.013, LAT0 + 0.013, "11 a 30 personas"),
        ("A4", "222222", LON0 + 0.003, LAT0 + 0.013, "0 a 5 personas"),
        ("A5", "333333", LON0 + 0.002, LAT0 + 0.001, "rango_desconocido"),
        ("A6", "333333", LON0 + 0.013, LAT0 + 0.003, "rango_desconocido"),
        ("A7", "999999", LON0 + 0.001, LAT0 + 0.002, "0 a 5 personas"),
        ("A8", "111111", LON0 - 0.30, LAT0 - 0.30, "0 a 5 personas"),
    ]
    return pd.DataFrame(
        rows, columns=["id", "codigo_act", "longitud", "latitud", "per_ocu"]
    ).assign(nom_estab=lambda d: "Estab " + d["id"])


def _crosswalk_table() -> pd.DataFrame:
    return pd.DataFrame({
        "scian_codigo": ["111111", "222222", "333333"],
        "sector_serio": ["SEC001", "SEC002", "SEC003"],
        "notas": ["", "", ""],
    })


@pytest.fixture
def wb() -> WarehouseBuilder:
    return WarehouseBuilder(serio_sectors=SERIO_SECTORS)


@pytest.fixture
def ageb_gdf() -> gpd.GeoDataFrame:
    return AGEBLoader().normalize(_make_ageb_grid_raw())


@pytest.fixture
def denue_gdf(wb) -> gpd.GeoDataFrame:
    denue_norm = DENUELoader().normalize(_make_denue_raw())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")
    return mapped


@pytest.fixture
def warehouse_files(tmp_path, wb, ageb_gdf, denue_gdf):
    """Corre Stage 5 completo y serializa a disco — insumo real de Stage 6."""
    warehouse = wb.build_from_gdfs(ageb_gdf, denue_gdf)
    parquet_path, metadata_path = wb.to_warehouse_files(
        warehouse,
        parquet_path=tmp_path / "warehouse.parquet",
        metadata_path=tmp_path / "metadata.json",
    )
    return {
        "parquet_path": parquet_path,
        "metadata_path": metadata_path,
        "warehouse": warehouse,
        "join_report": wb.join_report,
        "integrity_report": wb.integrity_report,
    }


# ══════════════════════════════════════════════════════════════════════════
# load_warehouse() / load_metadata() — solo lectura, sin recomputar nada
# ══════════════════════════════════════════════════════════════════════════
def test_load_warehouse_reads_parquet_unchanged(warehouse_files):
    gdf = load_warehouse(warehouse_files["parquet_path"])
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == len(warehouse_files["warehouse"]) == 5
    assert set(gdf["sector_serio"]) == {"SEC001", "SEC002", "SEC003"}


def test_load_warehouse_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_warehouse(tmp_path / "no_existe.parquet")


def test_load_metadata_reads_embedded_reports(warehouse_files):
    metadata = load_metadata(warehouse_files["metadata_path"])
    assert metadata["n_rows"] == 5
    assert metadata["join_report"]["n_total"] == 8
    assert metadata["integrity_report"]["n_ageb_sector_pairs"] == 5


def test_load_metadata_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_metadata(tmp_path / "no_existe.json")


def test_resolve_reports_uses_embedded_dicts_by_default(warehouse_files):
    metadata = load_metadata(warehouse_files["metadata_path"])
    join_report, integrity_report = resolve_reports(metadata)
    assert join_report["n_total"] == 8
    assert integrity_report["n_ageb_sector_pairs"] == 5


def test_resolve_reports_raises_if_neither_source_has_them():
    with pytest.raises(ValueError):
        resolve_reports({"n_rows": 0})


# ══════════════════════════════════════════════════════════════════════════
# compute_quality_report() — sin I/O, valores esperados iguales a Stage 5
# ══════════════════════════════════════════════════════════════════════════
def test_compute_quality_report_matches_known_stage5_numbers(warehouse_files):
    gdf = load_warehouse(warehouse_files["parquet_path"])
    metadata = load_metadata(warehouse_files["metadata_path"])
    join_report, integrity_report = resolve_reports(metadata)

    report = compute_quality_report(
        gdf, metadata, join_report, integrity_report,
        n_sectores_universo=len(SERIO_SECTORS),
    )

    assert isinstance(report, QualityReport)
    assert report.n_rows == 5

    ws = report.warehouse_summary
    assert ws["n_agebs_distintos"] == 4          # A00, A01, A10, A11
    assert ws["n_sectores_presentes"] == 3
    assert ws["n_sectores_universo"] == 3
    assert ws["sector_coverage_pct"] == pytest.approx(1.0)
    assert ws["total_establecimientos"] == 6      # A1..A6 (A7 sin sector, A8 huérfano)
    assert ws["total_empleo_faltante"] == 2       # A5, A6

    jc = report.join_consistency
    assert jc["n_total_denue"] == 8
    assert jc["n_matched"] == 7
    assert jc["n_orphan"] == 1
    assert jc["n_ambiguous"] == 0
    assert jc["establecimientos_en_warehouse"] == 6
    assert jc["n_matched_excluidos_del_warehouse"] == 1   # A7: asignado a AGEB, sin sector
    assert jc["consistente"] is True

    ic = report.integrity_consistency
    assert ic["n_ageb_sector_pairs_reportados"] == 5
    assert ic["n_ageb_sector_pairs_en_parquet"] == 5
    assert ic["row_count_consistente"] is True
    assert ic["n_invalid"] == 0
    assert ic["coverage_establecimientos"] == pytest.approx(6 / 8)
    assert ic["coverage_empleo"] == pytest.approx(1 - 2 / 6)

    # 1 exclusión de crosswalk incompleto → WARNING, no CRITICAL
    assert report.overall_status == "WARNING"
    assert any("crosswalk incompleto" in f for f in report.flags)


def test_compute_quality_report_omega_method_breakdown(warehouse_files):
    gdf = load_warehouse(warehouse_files["parquet_path"])
    metadata = load_metadata(warehouse_files["metadata_path"])
    join_report, integrity_report = resolve_reports(metadata)

    report = compute_quality_report(gdf, metadata, join_report, integrity_report)

    breakdown = report.omega_method_breakdown
    # SEC001 (A00,A11) y SEC002 (A01) usan 'empleo'; SEC003 (A00,A10) usa fallback
    assert breakdown["empleo"]["n_filas"] == 3
    assert breakdown["establecimientos"]["n_filas"] == 2
    assert breakdown["sin_datos"]["n_filas"] == 0
    assert breakdown["empleo"]["pct"] == pytest.approx(3 / 5)


def test_compute_quality_report_sector_distribution(warehouse_files):
    gdf = load_warehouse(warehouse_files["parquet_path"])
    metadata = load_metadata(warehouse_files["metadata_path"])
    join_report, integrity_report = resolve_reports(metadata)

    report = compute_quality_report(gdf, metadata, join_report, integrity_report)

    dist = report.sector_distribution
    assert "SEC003" in dist["sectores_sin_dato_de_empleo"]
    assert "SEC001" not in dist["sectores_sin_dato_de_empleo"]
    # SEC001 (10.5+20.5=31 empleo) es el sector con más empleo total
    assert max(dist["top_sectores_por_empleo"], key=dist["top_sectores_por_empleo"].get) == "SEC001"


def test_compute_quality_report_flags_row_count_mismatch(warehouse_files):
    gdf = load_warehouse(warehouse_files["parquet_path"])
    metadata = load_metadata(warehouse_files["metadata_path"])
    join_report, integrity_report = resolve_reports(metadata)

    integrity_report_corrupted = dict(integrity_report, n_ageb_sector_pairs=999)
    report = compute_quality_report(gdf, metadata, join_report, integrity_report_corrupted)

    assert report.integrity_consistency["row_count_consistente"] is False
    assert report.overall_status == "CRITICAL"
    assert any("INCONSISTENCIA" in f for f in report.flags)


def test_compute_quality_report_on_empty_warehouse():
    empty = gpd.GeoDataFrame(
        {"cvegeo": [], "sector_serio": [], "n_establecimientos": [], "empleo_total": [],
         "n_empleo_faltante": [], "omega": [], "omega_metodo": []},
        geometry=gpd.GeoSeries([], crs="EPSG:6372"),
    )
    join_report = {"n_total": 0, "n_matched": 0, "n_orphan": 0, "n_ambiguous": 0}
    integrity_report = {"n_ageb_sector_pairs": 0, "n_valid": 0, "n_invalid": 0}

    report = compute_quality_report(empty, {}, join_report, integrity_report, n_sectores_universo=3)

    assert report.n_rows == 0
    assert report.warehouse_summary["total_establecimientos"] == 0
    assert report.integrity_consistency["row_count_consistente"] is True


# ══════════════════════════════════════════════════════════════════════════
# generate_quality_report() — orquestación completa, escribe quality_report.json
# ══════════════════════════════════════════════════════════════════════════
def test_generate_quality_report_writes_json(tmp_path, warehouse_files):
    output_path = tmp_path / "quality_report.json"

    report = generate_quality_report(
        parquet_path=warehouse_files["parquet_path"],
        metadata_path=warehouse_files["metadata_path"],
        output_path=output_path,
        n_sectores_universo=len(SERIO_SECTORS),
    )

    assert output_path.exists()
    on_disk = json.loads(output_path.read_text(encoding="utf-8"))
    assert on_disk["n_rows"] == report.n_rows == 5
    assert on_disk["overall_status"] == report.overall_status


def test_generate_quality_report_does_not_write_when_write_false(tmp_path, warehouse_files):
    output_path = tmp_path / "quality_report.json"
    generate_quality_report(
        parquet_path=warehouse_files["parquet_path"],
        metadata_path=warehouse_files["metadata_path"],
        output_path=output_path,
        write=False,
    )
    assert not output_path.exists()


def test_generate_quality_report_supports_standalone_report_files(tmp_path, warehouse_files):
    """Cubre el caso donde join_report/integrity_report se serializaron
    aparte (SpatialJoinReport.to_json()/WarehouseIntegrityReport.to_json())
    en vez de vivir embebidos en metadata.json."""
    join_report_path = tmp_path / "join_report.json"
    integrity_report_path = tmp_path / "integrity_report.json"
    warehouse_files["join_report"].to_json(join_report_path)
    warehouse_files["integrity_report"].to_json(integrity_report_path)

    # metadata.json "vacío" de reportes — deben resolverse desde los standalone
    bare_metadata_path = tmp_path / "bare_metadata.json"
    bare_metadata_path.write_text(json.dumps({"n_rows": 5}), encoding="utf-8")

    report = generate_quality_report(
        parquet_path=warehouse_files["parquet_path"],
        metadata_path=bare_metadata_path,
        join_report_path=join_report_path,
        integrity_report_path=integrity_report_path,
        write=False,
    )
    assert report.join_consistency["n_total_denue"] == 8
    assert report.integrity_consistency["n_ageb_sector_pairs_reportados"] == 5


def test_generate_quality_report_raises_without_warehouse_parquet(tmp_path, warehouse_files):
    with pytest.raises(FileNotFoundError):
        generate_quality_report(
            parquet_path=tmp_path / "no_existe.parquet",
            metadata_path=warehouse_files["metadata_path"],
        )
