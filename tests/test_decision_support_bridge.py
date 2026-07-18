# tests/test_decision_support_bridge.py
"""
Pruebas de `app.helpers.decision_support_bridge` — el puente que
reemplazó la lógica de agregación duplicada que antes vivía en
`app/helpers/aggregation.py` (`build_ageb_universe`,
`build_community_summary`, `build_municipality_gdf`,
`build_municipality_summary`).

Mismo criterio que `tests/test_decision_support.py`: un
`warehouse.parquet` GENUINO (`WarehouseBuilder` + `AGEBLoader` +
`DENUELoader` + crosswalk real, Stage 5 CERRADO) y un
`sector_cluster.json` FALSO pero fiel al contrato exacto de
`scripts/build_sector_clusters.py` — nunca se mockea el motor ni se
recalcula Louvain aquí.

Estas pruebas verifican específicamente que el puente:
  1. Produce las mismas columnas legacy (`cvegeo`, `peso_total_ageb`,
     `ranking_estatal`, `n_sectores_ageb`, `sector_peso`, `peso`,
     `peso_economico`) que consumían `app/panels/*`,
     `app/components/map_view.py` y `app/components/search_sidebar.py`
     antes del refactor — para que ningún panel haya tenido que
     cambiar.
  2. Deriva correctamente los dos agregados de presentación que el
     motor no calcula (`municipios` completos por comunidad,
     `cluster_dominante` por municipio) usando SOLO columnas que ya
     produjo `spatial.decision_support` — nunca sobre pesos crudos del
     warehouse.
  3. Nunca inventa geometría: la adjunta desde `warehouse_gdf`.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.decision_support.report import build_decision_support_report
from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.matrix import SpatialMatrix
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

from app.helpers.decision_support_bridge import (
    attach_geometry,
    build_municipality_gdf,
    dominant_cluster_by_municipio,
    profiles_to_ageb_df,
    profiles_to_community_df,
    profiles_to_muni_df,
)

LON0, LAT0, CELL = -99.20, 19.40, 0.01
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]

# Grilla 3x2: municipio "014" en j=0 (predomina SEC001/SEC002 -> cluster 0),
# municipio "015" en j=1 (predomina SEC003 -> cluster 1) — mismo patrón que
# tests/test_decision_support.py, para que la derivación de comunidad
# dominante por municipio sea no trivial (dos municipios, dos clusters
# distintos, resultado esperado conocido de antemano).
_CELLS = {
    "2201400010001": (0, 0),
    "2201400010002": (1, 0),
    "2201400010003": (2, 0),
    "2201500010004": (0, 1),
    "2201500010005": (1, 1),
    "2201500010006": (2, 1),
}


def _square(i: int, j: int) -> Polygon:
    x0, y0 = LON0 + i * CELL, LAT0 + j * CELL
    return Polygon([(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)])


def _make_ageb_grid_raw() -> gpd.GeoDataFrame:
    polys, ids = [], []
    for cvegeo, (i, j) in _CELLS.items():
        polys.append(_square(i, j))
        ids.append(cvegeo)
    return gpd.GeoDataFrame({"cvegeo": ids, "geometry": polys}, crs="EPSG:4326")


def _make_denue_raw() -> pd.DataFrame:
    """SEC001/SEC002 (codigo_act 111111/222222) concentrados en AGEBs del
    municipio 014; SEC003 (333333) concentrado en AGEBs del municipio 015."""
    rows = [
        ("A1", "111111", LON0 + 0.003, LAT0 + 0.003, "0 a 5 personas"),
        ("A2", "222222", LON0 + 0.014, LAT0 + 0.003, "6 a 10 personas"),
        ("A3", "111111", LON0 + 0.024, LAT0 + 0.003, "11 a 30 personas"),
        ("A4", "333333", LON0 + 0.003, LAT0 + 0.014, "0 a 5 personas"),
        ("A5", "333333", LON0 + 0.014, LAT0 + 0.014, "rango_desconocido"),
        ("A6", "333333", LON0 + 0.024, LAT0 + 0.014, "0 a 5 personas"),
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
    return WarehouseBuilder(serio_sectors=REAL_SERIO_SECTORS)


@pytest.fixture
def ageb_gdf_raw() -> gpd.GeoDataFrame:
    return AGEBLoader().normalize(_make_ageb_grid_raw())


@pytest.fixture
def warehouse_gdf(wb, ageb_gdf_raw) -> gpd.GeoDataFrame:
    denue_norm = DENUELoader().normalize(_make_denue_raw())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")
    return wb.build_from_gdfs(ageb_gdf_raw, mapped)


@pytest.fixture
def spatial_matrix(tmp_path, ageb_gdf_raw) -> SpatialMatrix:
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(ageb_gdf_raw)
    gal_path, metadata_path = gb.to_graph_files(
        graph, gal_path=tmp_path / "graph.gal", metadata_path=tmp_path / "graph_metadata.json"
    )
    return SpatialMatrix.from_gal(gal_path, metadata_path)


@pytest.fixture
def cluster_artifact() -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "n_clusters": 2,
        "modularity": 0.5,
        "clusters": {
            "0": {
                "cluster_id": 0, "nombre": "Comunidad 0 — Sector Uno",
                "sectores": ["SEC001", "SEC002"], "n_sectores": 2,
                "centralidad_media": 0.8, "bl_media": 1.1, "fl_media": 0.9,
            },
            "1": {
                "cluster_id": 1, "nombre": "Comunidad 1 — Sector Tres",
                "sectores": ["SEC003"], "n_sectores": 1,
                "centralidad_media": 0.5, "bl_media": 0.7, "fl_media": 1.3,
            },
        },
        "sector_to_cluster": {"SEC001": 0, "SEC002": 0, "SEC003": 1},
    }


@pytest.fixture
def sector_names() -> dict:
    return {"SEC001": "Sector Uno", "SEC002": "Sector Dos", "SEC003": "Sector Tres"}


@pytest.fixture
def decision_report(warehouse_gdf, cluster_artifact, sector_names, spatial_matrix):
    return build_decision_support_report(
        warehouse_gdf, cluster_artifact, sector_names, spatial_matrix=spatial_matrix,
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. Columnas legacy — ningún panel debió tener que cambiar
# ══════════════════════════════════════════════════════════════════════════
def test_profiles_to_ageb_df_has_legacy_columns(decision_report):
    df = profiles_to_ageb_df(decision_report)
    assert not df.empty
    for col in ["cvegeo", "municipio", "cluster_id", "peso_total_ageb",
                "ranking_estatal", "n_sectores_ageb", "sector_peso",
                "cluster_nombre", "sector_dominante_nombre"]:
        assert col in df.columns, f"falta columna legacy '{col}'"
    # "ageb"/"peso_total"/"ranking"/"n_sectores"/"sector_dominante_peso"
    # son los nombres nativos del motor — no deben sobrevivir el renombre.
    for old_col in ["ageb", "peso_total", "ranking", "n_sectores", "sector_dominante_peso"]:
        assert old_col not in df.columns


def test_profiles_to_community_df_has_legacy_columns(decision_report):
    ageb_df = profiles_to_ageb_df(decision_report)
    df = profiles_to_community_df(decision_report, ageb_df)
    assert not df.empty
    for col in ["cluster_id", "nombre", "sectores", "n_agebs", "n_municipios",
                "peso_economico", "participacion_pct", "municipios", "color"]:
        assert col in df.columns
    assert "peso_total" not in df.columns


def test_profiles_to_muni_df_has_legacy_columns(decision_report):
    ageb_df = profiles_to_ageb_df(decision_report)
    df = profiles_to_muni_df(decision_report, ageb_df)
    assert not df.empty
    for col in ["municipio", "peso", "n_agebs", "cluster_dominante", "cluster_dominante_nombre"]:
        assert col in df.columns
    assert "peso_total" not in df.columns


# ══════════════════════════════════════════════════════════════════════════
# 2. Agregados de presentación derivados — nunca sobre pesos crudos
# ══════════════════════════════════════════════════════════════════════════
def test_community_municipios_is_full_list_not_only_principales(decision_report):
    """`community_profiles[...].municipios_principales` es top-N; el
    puente debe devolver la lista COMPLETA de municipios de la
    comunidad, derivada de `ageb_df` ya construido por el motor."""
    ageb_df = profiles_to_ageb_df(decision_report)
    community_df = profiles_to_community_df(decision_report, ageb_df)

    for _, row in community_df.iterrows():
        agebs_del_cluster = ageb_df[ageb_df["cluster_id"] == row["cluster_id"]]
        municipios_esperados = sorted(agebs_del_cluster["municipio"].dropna().unique().tolist())
        assert row["municipios"] == municipios_esperados


def test_dominant_cluster_by_municipio_matches_known_layout(decision_report):
    """Municipio 014 (SEC001/SEC002) debe dominar en cluster 0; municipio
    015 (SEC003) debe dominar en cluster 1 — layout conocido de la
    fixture. La derivación debe usar exclusivamente `peso_total_ageb`
    y `cluster_id` ya producidos por el motor, nunca warehouse crudo."""
    ageb_df = profiles_to_ageb_df(decision_report)
    dom = dominant_cluster_by_municipio(ageb_df)

    dom_by_muni = dict(zip(dom["municipio"], dom["cluster_dominante"]))
    assert dom_by_muni.get("014") == 0
    assert dom_by_muni.get("015") == 1


def test_dominant_cluster_empty_input_returns_empty_frame():
    empty = pd.DataFrame()
    dom = dominant_cluster_by_municipio(empty)
    assert dom.empty
    assert list(dom.columns) == ["municipio", "cluster_dominante", "peso_cluster_dominante"]


# ══════════════════════════════════════════════════════════════════════════
# 3. Geometría — nunca inventada, siempre tomada de warehouse_gdf
# ══════════════════════════════════════════════════════════════════════════
def test_attach_geometry_preserves_crs_and_row_count(decision_report, warehouse_gdf):
    ageb_df = profiles_to_ageb_df(decision_report)
    ageb_gdf = attach_geometry(ageb_df, warehouse_gdf)

    assert isinstance(ageb_gdf, gpd.GeoDataFrame)
    assert ageb_gdf.crs == warehouse_gdf.crs
    assert len(ageb_gdf) == len(ageb_df)
    assert "geometry" in ageb_gdf.columns
    assert ageb_gdf.geometry.notna().all()


def test_build_municipality_gdf_dissolves_by_municipio(decision_report, warehouse_gdf):
    ageb_df = profiles_to_ageb_df(decision_report)
    ageb_gdf = attach_geometry(ageb_df, warehouse_gdf)
    muni_df = profiles_to_muni_df(decision_report, ageb_gdf)
    muni_gdf = build_municipality_gdf(ageb_gdf, muni_df)

    assert isinstance(muni_gdf, gpd.GeoDataFrame)
    assert set(muni_gdf["municipio"]) == {"014", "015"}
    assert muni_gdf.geometry.notna().all()
    # El peso municipal viene del motor (`peso`), no de un recálculo local.
    for _, row in muni_gdf.iterrows():
        muni_row = muni_df[muni_df["municipio"] == row["municipio"]].iloc[0]
        assert row["peso"] == pytest.approx(muni_row["peso"])
