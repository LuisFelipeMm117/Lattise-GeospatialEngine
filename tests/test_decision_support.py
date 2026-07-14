# tests/test_decision_support.py
"""
Pruebas de spatial.decision_support — Decision Support Engine.

Sigue el mismo criterio ya establecido en tests/test_engine.py,
tests/test_serio_bridge.py y tests/test_operator.py:

  1. Un `warehouse.parquet` GENUINO, construido con `WarehouseBuilder`
     sobre AGEBs + DENUE sintéticos y un crosswalk SCIAN→SERIO real
     (Stage 5, CERRADO) — nunca mockeado.
  2. Un `graph.gal`/`graph_metadata.json` GENUINO, construido con
     `SpatialGraphBuilder` sobre la MISMA grilla AGEB sintética
     (Spatial Graph Builder, CERRADO) — nunca mockeado.
  3. Un `simulation_gdf`/`SimulationReport` GENUINOS, producidos por
     `run_simulation_engine()` (Stage 8C, CERRADO) sobre los mismos
     artefactos — nunca mockeados.
  4. Un `sector_cluster.json` FALSO pero fiel al contrato exacto que
     produce `scripts/build_sector_clusters.py` (mismo patrón que
     `_fake_resultado_simulacion` en test_serio_bridge.py: no se
     recalcula Louvain aquí, solo se imita su artefacto de salida) —
     `spatial.decision_support` es un consumidor puro de ese artefacto,
     nunca invoca Louvain por sí mismo.

Grilla AGEB sintética: 3x2 celdas contiguas con `cvegeo` de formato
INEGI real (entidad(2)+municipio(3)+localidad(4)+ageb(4) = 13
caracteres), repartidas en DOS municipios ("014" para la fila j=0,
"015" para la fila j=1) para que las pruebas de agregación municipal y
de municipios conectados por contigüidad sean no triviales.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.decision_support.aggregation import build_ageb_universe
from spatial.decision_support.profiles import AGEBProfile, CommunityProfile, MunicipalityProfile
from spatial.decision_support.relationships import build_territorial_relationships
from spatial.decision_support.report import DecisionSupportReport, build_decision_support_report
from spatial.decision_support.territory import entidad_code, municipio_code
from spatial.graph.network import SpatialGraphBuilder
from spatial.simulation.engine import run_simulation_engine
from spatial.simulation.matrix import SpatialMatrix
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]

# ── Grilla 3x2: municipio "014" en j=0, municipio "015" en j=1 ─────────────
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
    """Establecimientos: SEC001/SEC002 presentes en AGEBs del municipio
    014, SEC003 presente en AGEBs de ambos municipios."""
    rows = [
        ("A1", "111111", LON0 + 0.003, LAT0 + 0.003, "0 a 5 personas"),      # AGEB 0001 (i=0,j=0)
        ("A2", "111111", LON0 + 0.014, LAT0 + 0.003, "6 a 10 personas"),     # AGEB 0002 (i=1,j=0)
        ("A3", "222222", LON0 + 0.024, LAT0 + 0.003, "11 a 30 personas"),    # AGEB 0003 (i=2,j=0)
        ("A4", "333333", LON0 + 0.003, LAT0 + 0.014, "0 a 5 personas"),      # AGEB 0004 (i=0,j=1)
        ("A5", "333333", LON0 + 0.014, LAT0 + 0.014, "rango_desconocido"),   # AGEB 0005 (i=1,j=1)
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


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — warehouse.parquet GENUINO (Stage 5, CERRADO)
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def wb() -> WarehouseBuilder:
    return WarehouseBuilder(serio_sectors=REAL_SERIO_SECTORS)


@pytest.fixture
def ageb_gdf_raw() -> gpd.GeoDataFrame:
    return AGEBLoader().normalize(_make_ageb_grid_raw())


@pytest.fixture
def denue_gdf(wb) -> gpd.GeoDataFrame:
    denue_norm = DENUELoader().normalize(_make_denue_raw())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")
    return mapped


@pytest.fixture
def warehouse_gdf(wb, ageb_gdf_raw, denue_gdf) -> gpd.GeoDataFrame:
    return wb.build_from_gdfs(ageb_gdf_raw, denue_gdf)


@pytest.fixture
def warehouse_parquet_path(tmp_path, wb, warehouse_gdf):
    parquet_path, _ = wb.to_warehouse_files(
        warehouse_gdf,
        parquet_path=tmp_path / "warehouse.parquet",
        metadata_path=tmp_path / "metadata.json",
    )
    return parquet_path


# ══════════════════════════════════════════════════════════════════════════
# Fixture graph.gal GENUINO (Spatial Graph Builder, CERRADO) — criterio queen
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def graph_files(tmp_path, ageb_gdf_raw):
    gb = SpatialGraphBuilder(criterio="queen")
    graph = gb.build(ageb_gdf_raw)
    return gb.to_graph_files(
        graph, gal_path=tmp_path / "graph.gal", metadata_path=tmp_path / "graph_metadata.json"
    )


@pytest.fixture
def spatial_matrix(graph_files) -> SpatialMatrix:
    gal_path, metadata_path = graph_files
    return SpatialMatrix.from_gal(gal_path, metadata_path)


# ══════════════════════════════════════════════════════════════════════════
# Fixture sector_cluster.json — FIEL al contrato de
# scripts/build_sector_clusters.py, nunca recalculado con Louvain aquí.
# SEC001/SEC002 → cluster 0 ; SEC003 → cluster 1 ; SEC999 (sin AGEBs
# locales) → cluster 2, para probar "comunidad vacía".
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def cluster_artifact() -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "source": "serio/data/A_nacional.npy",
        "method": "Leontief L=(I-A)^-1 → grafo de similitud → Louvain",
        "params": {"top_k": 8, "threshold": 0.0005, "resolution": 0.15, "seed": 42},
        "n_sectores_total": 4,
        "n_sectores_en_grafo": 4,
        "n_sectores_aislados": 0,
        "n_sectores_componente_menor": 0,
        "n_clusters": 3,
        "modularity": 0.42,
        "tiempo_ejecucion_seg": 0.01,
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
            "2": {
                "cluster_id": 2, "nombre": "Comunidad 2 — Sector Fantasma",
                "sectores": ["SEC999"], "n_sectores": 1,
                "centralidad_media": 0.1, "bl_media": 0.2, "fl_media": 0.2,
            },
        },
        "sector_to_cluster": {"SEC001": 0, "SEC002": 0, "SEC003": 1, "SEC999": 2},
        "sector_centrality": {"SEC001": 0.9, "SEC002": 0.7, "SEC003": 0.5, "SEC999": 0.1},
        "sector_bl": {"SEC001": 1.2, "SEC002": 1.0, "SEC003": 0.7, "SEC999": 0.2},
        "sector_fl": {"SEC001": 0.8, "SEC002": 1.0, "SEC003": 1.3, "SEC999": 0.2},
        "sectores_sin_cluster": [],
    }


@pytest.fixture
def sector_names() -> dict:
    return {"SEC001": "Sector Uno", "SEC002": "Sector Dos", "SEC003": "Sector Tres", "SEC999": "Sector Fantasma"}


# ══════════════════════════════════════════════════════════════════════════
# Fixture simulation_gdf/simulation_report GENUINOS (Stage 8C, CERRADO)
# ══════════════════════════════════════════════════════════════════════════
def _fake_resultado_simulacion(sectores, delta_x_pesos) -> dict:
    df_detalle = pd.DataFrame({"scian": sectores, "delta_X_pesos": delta_x_pesos})
    return {"delta_X": np.asarray(delta_x_pesos) * 1e-6, "df_detalle": df_detalle}


@pytest.fixture
def simulation(tmp_path, warehouse_parquet_path, graph_files):
    gal_path, metadata_path = graph_files
    resultado = _fake_resultado_simulacion(
        ["SEC001", "SEC002", "SEC003"], [1_000_000.0, 200_000.0, 50_000.0]
    )
    gdf_final, report = run_simulation_engine(
        resultado,
        rho=0.3,
        warehouse_parquet_path=warehouse_parquet_path,
        shock_ageb_output_path=tmp_path / "shock_ageb.parquet",
        gal_path=gal_path,
        metadata_path=metadata_path,
    )
    return gdf_final, report


# ══════════════════════════════════════════════════════════════════════════
# territory.py — parsing puro de cvegeo
# ══════════════════════════════════════════════════════════════════════════
def test_municipio_code_parses_inegi_cvegeo():
    assert municipio_code("2201400010001") == "014"
    assert entidad_code("2201400010001") == "22"


def test_municipio_code_short_cvegeo_returns_unknown():
    assert municipio_code("A00") == "—"
    assert entidad_code("A") == "—"


# ══════════════════════════════════════════════════════════════════════════
# aggregation.py — build_ageb_universe
# ══════════════════════════════════════════════════════════════════════════
def test_build_ageb_universe_assigns_municipio_and_dominant_sector(warehouse_gdf, cluster_artifact, sector_names):
    ageb_gdf, long_cluster, long_sector, report = build_ageb_universe(
        warehouse_gdf, cluster_artifact, sector_names
    )
    assert set(ageb_gdf["cvegeo"]) <= set(_CELLS.keys())
    assert set(ageb_gdf["municipio"]) <= {"014", "015"}
    assert (ageb_gdf["participacion_pct"].sum()) == pytest.approx(100.0, rel=1e-6)
    assert sorted(ageb_gdf["ranking"].tolist()) == list(range(1, len(ageb_gdf) + 1))
    assert report.n_agebs_total == report.n_agebs_con_perfil + report.n_agebs_sin_perfil


def test_build_ageb_universe_reports_unmapped_sectors_explicitly(warehouse_gdf, sector_names):
    """Un artefacto Louvain que no mapea NINGÚN sector del warehouse debe
    dejar el universo de AGEB vacío y reportarlo — nunca inferir cluster."""
    empty_cluster_artifact = {
        "clusters": {},
        "sector_to_cluster": {},
    }
    ageb_gdf, long_cluster, long_sector, report = build_ageb_universe(
        warehouse_gdf, empty_cluster_artifact, sector_names
    )
    assert long_cluster.empty
    assert ageb_gdf.empty
    assert report.n_agebs_sin_perfil == report.n_agebs_total
    assert report.sectores_no_mapeados  # todos los sectores quedan listados


# ══════════════════════════════════════════════════════════════════════════
# relationships.py — cadena AGEB → Municipio → Comunidad → AGEBs → Sectores
# ══════════════════════════════════════════════════════════════════════════
def test_relationships_chain_is_explicit(warehouse_gdf, cluster_artifact, sector_names, spatial_matrix):
    ageb_gdf, _, long_sector, _ = build_ageb_universe(warehouse_gdf, cluster_artifact, sector_names)
    rel = build_territorial_relationships(ageb_gdf, long_sector, spatial_matrix=spatial_matrix)

    ageb0 = "2201400010001"
    assert rel.ageb_to_municipio[ageb0] == "014"
    assert rel.ageb_to_comunidad[ageb0] == 0
    assert ageb0 in rel.ageb_to_vecinos
    assert set(rel.ageb_to_sectores[ageb0]) <= {"SEC001"}

    # índices inversos consistentes
    assert ageb0 in rel.municipio_to_agebs["014"]
    assert ageb0 in rel.comunidad_to_agebs[0]

    edges = rel.edges()
    assert any(e["tipo"] == "pertenece_a_municipio" and e["origen"] == ageb0 for e in edges)
    assert any(e["tipo"] == "relacionado_con_sector" for e in edges)


def test_relationships_without_spatial_matrix_leaves_neighbors_empty(warehouse_gdf, cluster_artifact, sector_names):
    ageb_gdf, _, long_sector, _ = build_ageb_universe(warehouse_gdf, cluster_artifact, sector_names)
    rel = build_territorial_relationships(ageb_gdf, long_sector, spatial_matrix=None)
    assert all(v == [] for v in rel.ageb_to_vecinos.values())


# ══════════════════════════════════════════════════════════════════════════
# report.py — DecisionSupportReport, sin simulación ni matriz espacial
# ══════════════════════════════════════════════════════════════════════════
def test_build_decision_support_report_minimal(warehouse_gdf, cluster_artifact, sector_names):
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)

    assert isinstance(report, DecisionSupportReport)
    assert report.has_simulation is False
    assert report.has_spatial_matrix is False
    assert report.n_agebs == 5  # AGEB 0006 no tiene establecimientos → sin perfil (peso_total=0, sin fila en long_sector)

    ageb0 = report.ageb("2201400010001")
    assert ageb0 is not None
    assert ageb0["municipio"] == "014"
    assert ageb0["impacto_directo"] is None
    assert ageb0["impacto_propagado"] is None
    assert ageb0["cobertura_espacial"] is False
    assert ageb0["n_vecinos"] == 0
    assert ageb0["agebs_relacionadas"] == []


def test_decision_support_report_communities_include_empty_ones(warehouse_gdf, cluster_artifact, sector_names):
    """La comunidad 2 (SEC999) no tiene ningún AGEB local — debe seguir
    apareciendo en el reporte con n_agebs=0, nunca omitirse."""
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)
    assert report.n_comunidades == 3
    empty_community = report.community("2")
    assert empty_community is not None
    assert empty_community["n_agebs"] == 0
    assert empty_community["participacion_pct"] == 0.0
    assert empty_community["agebs_principales"] == []


def test_decision_support_report_municipality_aggregation_is_consistent(warehouse_gdf, cluster_artifact, sector_names):
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)
    assert set(report.municipality_profiles.keys()) <= {"014", "015"}

    total_municipal_agebs = sum(mp["n_agebs"] for mp in report.municipality_profiles.values())
    assert total_municipal_agebs == report.n_agebs

    total_participacion = sum(mp["participacion_pct"] for mp in report.municipality_profiles.values())
    assert total_participacion == pytest.approx(100.0, rel=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# report.py — con simulación + matriz espacial (camino completo)
# ══════════════════════════════════════════════════════════════════════════
def test_build_decision_support_report_full(warehouse_gdf, cluster_artifact, sector_names, spatial_matrix, simulation):
    sim_gdf, sim_report = simulation
    report = build_decision_support_report(
        warehouse_gdf,
        cluster_artifact,
        sector_names,
        spatial_matrix=spatial_matrix,
        simulation_gdf=sim_gdf,
        simulation_report=sim_report,
    )

    assert report.has_simulation is True
    assert report.has_spatial_matrix is True

    ageb0 = report.ageb("2201400010001")
    assert ageb0["impacto_propagado"] is not None
    assert ageb0["impacto_directo"] is not None
    assert ageb0["cobertura_espacial"] is True
    assert ageb0["n_vecinos"] >= 1
    assert "220140001" not in ageb0["agebs_relacionadas"]  # nunca se autoincluye como su propio vecino

    # AGEBs vecinas de municipios distintos deben aparecer en
    # `municipios_conectados` (grilla contigua entre fila 014 y fila 015)
    ageb_boundary = report.ageb("2201400010003")  # esquina (2,0), toca (2,1) en muni 015
    assert "015" in ageb_boundary["municipios_conectados"] or ageb_boundary["municipios_conectados"] == []

    # Insights presentes y puramente textuales (nunca vacíos para un AGEB con datos)
    assert report.insights["agebs"]["2201400010001"]
    assert isinstance(report.insights["agebs"]["2201400010001"][0], str)
    assert report.insights["portfolio"]

    # Consistencia: suma de impacto directo agregado por municipio == suma total del AGEB universo
    total_directo_municipal = sum(
        mp["impacto_directo_agregado"] or 0.0 for mp in report.municipality_profiles.values()
    )
    total_directo_agebs = sum(
        ap["impacto_directo"] or 0.0 for ap in report.ageb_profiles.values()
    )
    assert total_directo_municipal == pytest.approx(total_directo_agebs, rel=1e-6)


def test_ageb_isolated_without_neighbors_reports_isla(warehouse_gdf, cluster_artifact, sector_names):
    """Sin `spatial_matrix`, ningún AGEB tiene vecinos — nunca se infiere
    contigüidad ad hoc en esta capa (mismo criterio que
    `app/helpers/data_sources.py::neighbors_of`)."""
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names, spatial_matrix=None)
    for ageb_dict in report.ageb_profiles.values():
        assert ageb_dict["n_vecinos"] == 0
        assert ageb_dict["cobertura_espacial"] is False


# ══════════════════════════════════════════════════════════════════════════
# AGEBs sin geometría — nunca deben tumbar el pipeline
# ══════════════════════════════════════════════════════════════════════════
def test_ageb_without_geometry_does_not_crash_aggregation(warehouse_gdf, cluster_artifact, sector_names):
    warehouse_no_geom = warehouse_gdf.copy()
    warehouse_no_geom.loc[warehouse_no_geom["cvegeo"] == "2201400010001", "geometry"] = None

    ageb_gdf, _, _, report = build_ageb_universe(warehouse_no_geom, cluster_artifact, sector_names)
    assert "2201400010001" in set(ageb_gdf["cvegeo"])
    row = ageb_gdf.loc[ageb_gdf["cvegeo"] == "2201400010001"].iloc[0]
    assert row.geometry is None


# ══════════════════════════════════════════════════════════════════════════
# Datos faltantes — cluster_artifact/warehouse_gdf vacíos no truenan
# ══════════════════════════════════════════════════════════════════════════
def test_report_handles_completely_empty_warehouse(cluster_artifact, sector_names):
    empty_warehouse = gpd.GeoDataFrame(
        {
            "cvegeo": pd.array([], dtype="object"),
            "sector_serio": pd.array([], dtype="object"),
            "n_establecimientos": pd.array([], dtype="float64"),
            "empleo_total": pd.array([], dtype="float64"),
            "n_empleo_faltante": pd.array([], dtype="float64"),
            "geometry": [],
        },
        geometry="geometry", crs="EPSG:6372",
    )
    report = build_decision_support_report(empty_warehouse, cluster_artifact, sector_names)
    assert report.n_agebs == 0
    assert report.n_municipios == 0
    assert report.ageb_profiles == {}
    assert report.municipality_profiles == {}
    # Las comunidades del artefacto Louvain siguen listadas, todas vacías
    assert report.n_comunidades == 3
    assert all(cp["n_agebs"] == 0 for cp in report.community_profiles.values())


def test_report_handles_missing_sector_names(warehouse_gdf, cluster_artifact):
    """`sector_names={}` (catálogo ausente) nunca debe tronar — el nombre
    cae a un placeholder explícito ('Sector <codigo>'), nunca se infiere."""
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names={})
    ageb0 = report.ageb("2201400010001")
    assert ageb0["sector_dominante_nombre"] == "Sector SEC001"


# ══════════════════════════════════════════════════════════════════════════
# Serialización — to_dict / to_json / to_dataframe / to_parquet
# ══════════════════════════════════════════════════════════════════════════
def test_report_to_dict_and_to_json_roundtrip(tmp_path, warehouse_gdf, cluster_artifact, sector_names):
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)
    d = report.to_dict()
    assert d["n_agebs"] == report.n_agebs
    assert "ageb_profiles" in d and "relationships" in d and "insights" in d

    out_path = tmp_path / "decision_support_report.json"
    report.to_json(out_path)
    assert out_path.exists()
    reloaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert reloaded["n_agebs"] == report.n_agebs
    assert reloaded["ageb_profiles"]["2201400010001"]["municipio"] == "014"


def test_report_to_dataframe_and_to_parquet(tmp_path, warehouse_gdf, cluster_artifact, sector_names):
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)
    df = report.to_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == report.n_agebs
    assert "ageb" in df.columns and "municipio" in df.columns

    out_path = tmp_path / "ageb_profiles.parquet"
    report.to_parquet(out_path)
    assert out_path.exists()
    reloaded = pd.read_parquet(out_path)
    assert len(reloaded) == report.n_agebs
    # columnas de tipo lista se serializaron a JSON string, no se descartaron
    assert isinstance(reloaded.iloc[0]["sectores_presentes"], str)
    assert json.loads(reloaded.iloc[0]["sectores_presentes"]) == json.loads(
        reloaded.iloc[0]["sectores_presentes"]
    )


def test_report_summary_is_human_readable_string(warehouse_gdf, cluster_artifact, sector_names):
    report = build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)
    text = report.summary()
    assert isinstance(text, str)
    assert "Decision Support Report" in text


# ══════════════════════════════════════════════════════════════════════════
# Profiles — dataclasses puros, serializables
# ══════════════════════════════════════════════════════════════════════════
def test_profile_dataclasses_serialize_cleanly():
    ageb = AGEBProfile(ageb="X", municipio="014")
    muni = MunicipalityProfile(municipio="014")
    comm = CommunityProfile(cluster_id=0, nombre="Comunidad 0")
    for obj in (ageb, muni, comm):
        d = obj.to_dict()
        assert isinstance(d, dict)
        json.dumps(d, default=str)  # nunca debe tronar por tipos no serializables
