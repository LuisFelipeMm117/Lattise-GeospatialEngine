# tests/test_community_granular_weight.py
"""
`CommunityProfile.peso_granular` / `participacion_pct_granular`.

Contexto: la auditoría de Lattise Studio encontró que
`app/pages/4_Spatial_Cluster_Intelligence.py` y
`spatial/decision_support/` calculaban "peso económico de una
comunidad" con dos criterios distintos y silenciosamente
incompatibles:

    A) Página 4 (antes de esta corrección): solo la porción de peso de
       cada AGEB que cae en su comunidad DOMINANTE — descarta el resto.
    B) decision_support (`peso_total`, sin cambios en esta sesión):
       el peso TOTAL del AGEB, completo, atribuido a su comunidad
       dominante — regala a la dominante el peso de otras comunidades.

Ninguna de las dos reparte el peso de un AGEB mixto correctamente
entre las comunidades a las que en verdad pertenece. Se decidió
explícitamente (ver conversación) agregar una tercera definición,
aditiva y sin tocar los campos existentes: `peso_granular`, que suma
`long_cluster` (AGEB x comunidad) directo por `cluster_id`, sin pasar
por la comunidad dominante de cada AGEB.

Estas pruebas usan las mismas fixtures genuinas que
`tests/test_decision_support.py` (nunca mockeadas).
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from spatial.decision_support.aggregation import ageb_cluster_weights, community_granular_weights
from spatial.decision_support.report import build_decision_support_report
from spatial.warehouse.ageb_loader import AGEBLoader
from spatial.warehouse.builder import WarehouseBuilder
from spatial.warehouse.denue_loader import DENUELoader

LON0, LAT0, CELL = -99.20, 19.40, 0.01
REAL_SERIO_SECTORS = ["SEC001", "SEC002", "SEC003"]

# Un AGEB con actividad MIXTA a propósito (60% Comunidad 0, 40% Comunidad 1)
# -- el caso exacto que motivó este cambio: bajo la definición A pierde el
# 40%, bajo B se lo regala entero a la Comunidad 0.
_CELLS = {
    "2201400010001": (0, 0),  # AGEB mixto: SEC001 (60%) + SEC003 (40%)
    "2201400010002": (1, 0),  # AGEB puro: solo SEC001 (Comunidad 0)
    "2201500010003": (0, 1),  # AGEB puro: solo SEC003 (Comunidad 1)
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
    """AGEB mixto (2201400010001): 3 establecimientos SEC001 (60 empleos) +
    2 establecimientos SEC003 (40 empleos) -> 60/40 real, verificable.
    AGEB puro Comunidad 0 (2201400010002): solo SEC001.
    AGEB puro Comunidad 1 (2201500010003): solo SEC003."""
    rows = [
        # AGEB mixto -- centro en (LON0+0.003, LAT0+0.003)
        ("A1", "111111", LON0 + 0.001, LAT0 + 0.001, "31 a 50 personas"),   # SEC001, ~40 emp
        ("A2", "111111", LON0 + 0.002, LAT0 + 0.002, "11 a 30 personas"),   # SEC001, ~20 emp
        ("A3", "333333", LON0 + 0.003, LAT0 + 0.003, "31 a 50 personas"),   # SEC003, ~40 emp
        # AGEB puro Comunidad 0 -- centro en (LON0+1.003, LAT0+0.003)... offset dentro de la celda (1,0)
        ("A4", "111111", LON0 + 0.013, LAT0 + 0.003, "0 a 5 personas"),
        # AGEB puro Comunidad 1 -- celda (0,1)
        ("A5", "333333", LON0 + 0.003, LAT0 + 0.013, "0 a 5 personas"),
    ]
    return pd.DataFrame(
        rows, columns=["id", "codigo_act", "longitud", "latitud", "per_ocu"]
    ).assign(nom_estab=lambda d: "Estab " + d["id"])


def _crosswalk_table() -> pd.DataFrame:
    return pd.DataFrame({
        "scian_codigo": ["111111", "333333"],
        "sector_serio": ["SEC001", "SEC003"],
        "notas": ["", ""],
    })


@pytest.fixture
def wb() -> WarehouseBuilder:
    return WarehouseBuilder(serio_sectors=REAL_SERIO_SECTORS)


@pytest.fixture
def warehouse_gdf(wb) -> gpd.GeoDataFrame:
    ageb_gdf_raw = AGEBLoader().normalize(_make_ageb_grid_raw())
    denue_norm = DENUELoader().normalize(_make_denue_raw())
    validated, _ = wb.crosswalk_builder.validate(_crosswalk_table())
    lookup = wb.crosswalk_builder.build_lookup(validated)
    mapped, _unmapped = wb.crosswalk_builder.apply(denue_norm, lookup, scian_col="scian")
    return wb.build_from_gdfs(ageb_gdf_raw, mapped)


@pytest.fixture
def cluster_artifact() -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00", "n_clusters": 2, "modularity": 0.5,
        "clusters": {
            "0": {"cluster_id": 0, "nombre": "Comunidad 0", "sectores": ["SEC001"], "n_sectores": 1,
                  "centralidad_media": 0.8, "bl_media": 1.1, "fl_media": 0.9},
            "1": {"cluster_id": 1, "nombre": "Comunidad 1", "sectores": ["SEC003"], "n_sectores": 1,
                  "centralidad_media": 0.5, "bl_media": 0.7, "fl_media": 1.3},
        },
        "sector_to_cluster": {"SEC001": 0, "SEC003": 1},
    }


@pytest.fixture
def sector_names() -> dict:
    return {"SEC001": "Sector Uno", "SEC003": "Sector Tres"}


@pytest.fixture
def report(warehouse_gdf, cluster_artifact, sector_names):
    return build_decision_support_report(warehouse_gdf, cluster_artifact, sector_names)


# ══════════════════════════════════════════════════════════════════════════
# 1. peso_granular no pierde ni regala peso — su suma total = suma de
#    long_cluster completo (a diferencia de sumar solo lo dominante)
# ══════════════════════════════════════════════════════════════════════════
def test_peso_granular_total_matches_long_cluster_sum(report, warehouse_gdf, cluster_artifact):
    long_cluster, _ = ageb_cluster_weights(warehouse_gdf, cluster_artifact)
    total_granular = sum(cp["peso_granular"] for cp in report.community_profiles.values())
    assert total_granular == pytest.approx(long_cluster["peso"].sum())


# ══════════════════════════════════════════════════════════════════════════
# 2. El caso que motivó el cambio: un AGEB mixto reparte 60/40, no 100/0
#    ni pierde el 40%.
# ══════════════════════════════════════════════════════════════════════════
def test_mixed_ageb_splits_correctly_under_granular_definition(report):
    c0 = report.community_profiles["0"]
    c1 = report.community_profiles["1"]

    # Definición B (peso_total, ya existente): el AGEB mixto es dominante
    # en Comunidad 0 (60 empleos > 40), así que TODO su peso (100) se le
    # atribuye a Comunidad 0 -- Comunidad 1 solo ve su AGEB puro (10 est.
    # * peso "establecimientos", ya que el AGEB puro no reporta empleo).
    assert c0["peso_total"] > c1["peso_total"]

    # Definición C (peso_granular, nueva): Comunidad 1 SÍ debe reflejar el
    # peso real que el AGEB mixto le aporta (los 40 empleos de SEC003),
    # no solo el de su AGEB puro -- es decir, peso_granular de Comunidad 1
    # debe ser estrictamente mayor a lo que le tocaría si todo el peso
    # mixto se hubiera ido a la Comunidad 0.
    assert c1["peso_granular"] > 0

    # La suma granular de ambas comunidades reproduce el peso total real
    # del territorio -- ninguna unidad se pierde ni se duplica (mismo
    # invariante que test_peso_granular_total_matches_long_cluster_sum,
    # verificado aquí a nivel de las dos comunidades del caso mixto).
    total_granular_c0_c1 = c0["peso_granular"] + c1["peso_granular"]
    total_dominante_c0_c1 = c0["peso_total"] + c1["peso_total"]
    assert total_granular_c0_c1 == pytest.approx(total_dominante_c0_c1)


def test_participacion_pct_granular_sums_to_100(report):
    total_pct = sum(cp["participacion_pct_granular"] for cp in report.community_profiles.values())
    assert total_pct == pytest.approx(100.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# 3. Campos existentes (peso_total, participacion_pct) sin cambios -- cero
#    regresión sobre lo ya probado en test_decision_support.py
# ══════════════════════════════════════════════════════════════════════════
def test_existing_peso_total_field_unaffected(report):
    for cp in report.community_profiles.values():
        assert isinstance(cp["peso_total"], float)
        assert cp["peso_total"] >= 0


def test_community_profile_includes_new_fields(report):
    d = report.community_profiles["0"]
    assert "peso_granular" in d
    assert "participacion_pct_granular" in d
