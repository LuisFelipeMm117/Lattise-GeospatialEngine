# tests/test_cluster_intelligence_bridge.py
"""
Pruebas de `app.helpers.cluster_intelligence_bridge` -- el puente que
cerro la tercera copia de agregacion (`4_Spatial_Cluster_Intelligence.py`
tenia su propia `_ageb_cluster_weights`/`build_community_summary`/
`build_municipality_gdf`, paralela a `spatial.decision_support` y a la
version usada por `5_Opportunity_Explorer.py`).

Corren contra los artefactos REALES ya presentes en el repo
(`data/warehouse/warehouse.parquet`, `data/analytics/sector_cluster.json`,
`serio/data/sectores.csv`) -- no se mockea nada, mismo criterio que el
resto de la suite. Se saltan si esos artefactos no estan presentes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import json
import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_WAREHOUSE = _REPO_ROOT / "data" / "warehouse" / "warehouse.parquet"
_CLUSTER_JSON = _REPO_ROOT / "data" / "analytics" / "sector_cluster.json"
_SECTORES_CSV = _REPO_ROOT / "serio" / "data" / "sectores.csv"

pytestmark = pytest.mark.skipif(
    not (_WAREHOUSE.exists() and _CLUSTER_JSON.exists() and _SECTORES_CSV.exists()),
    reason="Artefactos congelados no estan presentes en este entorno.",
)

from app.helpers.cluster_intelligence_bridge import (  # noqa: E402
    aggregate_shock_by,
    build_ageb_and_long,
    build_community_summary,
    build_municipality_gdf_and_summary,
)
from spatial.decision_support.aggregation import ageb_cluster_weights  # noqa: E402
from spatial.decision_support.report import build_decision_support_report  # noqa: E402


@pytest.fixture(scope="module")
def warehouse_gdf():
    return gpd.read_parquet(_WAREHOUSE)


@pytest.fixture(scope="module")
def artifact():
    with open(_CLUSTER_JSON, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sector_names():
    df = pd.read_csv(_SECTORES_CSV, dtype={"scian": str})
    return dict(zip(df["scian"].astype(str), df["nombre"].astype(str)))


@pytest.fixture(scope="module")
def ageb_and_long(warehouse_gdf, artifact, sector_names):
    return build_ageb_and_long(warehouse_gdf, artifact, sector_names)


@pytest.fixture(scope="module")
def decision_report(warehouse_gdf, artifact, sector_names):
    return build_decision_support_report(warehouse_gdf, artifact, sector_names)


# ══════════════════════════════════════════════════════════════════════════
# 1. ageb_gdf/long_df -- mismas columnas legacy que consumian los 6 Layers
# ══════════════════════════════════════════════════════════════════════════
def test_ageb_gdf_has_legacy_peso_column_not_cluster_peso(ageb_and_long):
    ageb_gdf, long_df, long_sector, integrity_report = ageb_and_long
    assert "peso" in ageb_gdf.columns
    assert "cluster_peso" not in ageb_gdf.columns
    for col in ("cvegeo", "cluster_id", "peso_metodo", "peso_total_ageb", "municipio", "geometry"):
        assert col in ageb_gdf.columns


def test_long_df_matches_ageb_cluster_weights_directly(ageb_and_long, warehouse_gdf, artifact):
    _, long_df, _, _ = ageb_and_long
    expected, _ = ageb_cluster_weights(warehouse_gdf, artifact)
    assert long_df["peso"].sum() == pytest.approx(expected["peso"].sum())
    assert set(long_df.columns) == set(expected.columns)


def test_integrity_report_has_legacy_key_names(ageb_and_long):
    _, _, _, integrity_report = ageb_and_long
    assert "n_agebs_asignados" in integrity_report
    assert "n_agebs_sin_asignacion" in integrity_report
    assert integrity_report["n_agebs_asignados"] == integrity_report["n_agebs_con_perfil"]


# ══════════════════════════════════════════════════════════════════════════
# 2. community_summary -- usa peso_granular, no peso_total ni el criterio
#    "solo dominante" que tenia la pagina antes de esta correccion
# ══════════════════════════════════════════════════════════════════════════
def test_community_summary_uses_granular_weight_not_dominant_only(ageb_and_long, decision_report):
    ageb_gdf, _, _, _ = ageb_and_long
    community_summary = build_community_summary(decision_report, ageb_gdf)

    # El total de peso_economico debe reproducir el peso GRANULAR total
    # del territorio (definicion C), NO el total "solo dominante"
    # (definicion A, la que tenia la pagina antes -- seria ~65% menor).
    total_granular_engine = sum(cp["peso_granular"] for cp in decision_report.community_profiles.values())
    assert community_summary["peso_economico"].sum() == pytest.approx(total_granular_engine)

    total_dominante_only = ageb_gdf.groupby("cluster_id")["peso"].sum().sum()
    # La definicion granular nunca es menor a la "solo dominante" -- por
    # construccion, siempre es mayor o igual (nunca pierde peso).
    assert community_summary["peso_economico"].sum() >= total_dominante_only


def test_community_summary_has_full_municipios_list(ageb_and_long, decision_report):
    ageb_gdf, _, _, _ = ageb_and_long
    community_summary = build_community_summary(decision_report, ageb_gdf)
    for _, row in community_summary.iterrows():
        agebs_del_cluster = ageb_gdf[ageb_gdf["cluster_id"] == row["cluster_id"]]
        esperado = sorted(agebs_del_cluster["municipio"].dropna().unique().tolist())
        assert row["municipios"] == esperado


def test_community_participacion_pct_sums_to_100(ageb_and_long, decision_report):
    ageb_gdf, _, _, _ = ageb_and_long
    community_summary = build_community_summary(decision_report, ageb_gdf)
    assert community_summary["participacion_pct"].sum() == pytest.approx(100.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# 3. municipality -- peso viene de MunicipalityProfile.peso_total (siempre
#    correcto, nunca funcionado a traves de dominancia de comunidad)
# ══════════════════════════════════════════════════════════════════════════
def test_municipality_peso_matches_decision_support_total(ageb_and_long, decision_report):
    ageb_gdf, long_cluster, _, _ = ageb_and_long
    community_summary = build_community_summary(decision_report, ageb_gdf)
    muni_gdf, muni_summary = build_municipality_gdf_and_summary(
        ageb_gdf, long_cluster, decision_report, community_summary
    )
    for _, row in muni_summary.iterrows():
        expected = decision_report.municipality_profiles[row["municipio"]]["peso_total"]
        assert row["peso"] == pytest.approx(expected)


def test_municipality_gdf_has_geometry_and_matches_summary_rows(ageb_and_long, decision_report):
    ageb_gdf, long_cluster, _, _ = ageb_and_long
    community_summary = build_community_summary(decision_report, ageb_gdf)
    muni_gdf, muni_summary = build_municipality_gdf_and_summary(
        ageb_gdf, long_cluster, decision_report, community_summary
    )
    assert isinstance(muni_gdf, gpd.GeoDataFrame)
    assert muni_gdf.geometry.notna().all()
    assert set(muni_gdf["municipio"]) == set(muni_summary["municipio"])


# ══════════════════════════════════════════════════════════════════════════
# 4. aggregate_shock_by -- utilidad trivial, sin simulacion no se prueba
#    su valor (no hay sim_gdf disponible en este entorno), solo su forma
# ══════════════════════════════════════════════════════════════════════════
def test_aggregate_shock_by_empty_id_map_returns_empty():
    from spatial.simulation.engine import (
        IMPACTO_DIRECTO_COL,
        IMPACTO_INDIRECTO_COL,
        IMPACTO_PROPAGADO_COL,
    )
    sim_gdf = gpd.GeoDataFrame({
        "cvegeo": [], IMPACTO_DIRECTO_COL: [], IMPACTO_INDIRECTO_COL: [], IMPACTO_PROPAGADO_COL: [],
        "geometry": [],
    })
    id_map = pd.DataFrame({"cvegeo": [], "cluster_id": []})
    out = aggregate_shock_by(sim_gdf, id_map, "cluster_id")
    assert out.empty
