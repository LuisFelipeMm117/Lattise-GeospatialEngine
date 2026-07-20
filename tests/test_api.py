# tests/test_api.py
"""
Stage 10 — pruebas de la API REST.

Corren contra los artefactos REALES ya presentes en el repo
(`serio/data/`, `data/warehouse/warehouse.parquet`,
`data/analytics/sector_cluster.json`, `data/graph/graph.gal`) usando el
`EngineState` por defecto — no se mockea nada del motor, mismo criterio
que el resto de la suite. Si estos artefactos no están presentes en el
entorno donde corre pytest (p.ej. un clon fresco sin haber corrido el
pipeline), estas pruebas se saltan explícitamente en vez de fallar de
forma confusa.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.app import create_app
from api.state import EngineState

_state = EngineState()
_ARTIFACTS_READY = all(_state.readiness().values())

pytestmark = pytest.mark.skipif(
    not _ARTIFACTS_READY,
    reason="Artefactos congelados (warehouse.parquet / sector_cluster.json / graph.gal / serio/data) "
           "no están presentes en este entorno — correr el pipeline offline primero.",
)


@pytest.fixture
def client():
    app = create_app(EngineState())
    app.testing = True
    return app.test_client()


# ══════════════════════════════════════════════════════════
# /health
# ══════════════════════════════════════════════════════════
def test_health_ok(client):
    resp = client.get("/health")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["status"] == "ok"
    assert all(body["artifacts"].values())


def test_health_reports_missing_artifact():
    """Con un EngineState apuntando a una ruta inexistente, /health debe
    responder 503 y marcar exactamente ese artefacto como faltante —
    nunca debe intentar regenerarlo."""
    broken_state = EngineState(warehouse_parquet=Path("/tmp/no_existe_warehouse.parquet"))
    app = create_app(broken_state)
    app.testing = True
    resp = app.test_client().get("/health")
    body = resp.get_json()
    assert resp.status_code == 503
    assert body["status"] == "degraded"
    assert body["artifacts"]["warehouse"] is False


# ══════════════════════════════════════════════════════════
# /catalog
# ══════════════════════════════════════════════════════════
def test_catalog_lists_estados_y_sectores(client):
    resp = client.get("/catalog")
    body = resp.get_json()
    assert resp.status_code == 200
    assert "Aguascalientes" in body["estados"]
    assert body["n_estados"] == len(body["estados"])
    assert body["n_sectores"] == len(body["sectores"])
    assert {"scian", "nombre"} == set(body["sectores"][0].keys())


# ══════════════════════════════════════════════════════════
# /simulate — Scenario (Stage 8D), sin recalcular nada localmente
# ══════════════════════════════════════════════════════════
def test_simulate_missing_fields_returns_400(client):
    resp = client.post("/simulate", json={"estado": "Aguascalientes"})
    assert resp.status_code == 400
    assert "campos_faltantes" in resp.get_json()


def test_simulate_unknown_estado_returns_400(client):
    resp = client.post(
        "/simulate",
        json={"estado": "Estado Que No Existe", "sector": "111", "monto": 1_000_000, "rho": 0.3},
    )
    assert resp.status_code == 400


def test_simulate_real_scenario_matches_scenario_report(client):
    """El endpoint debe devolver EXACTAMENTE lo mismo que
    `Scenario.run(...).to_dict()` — no una copia reformulada."""
    body = {"estado": "Aguascalientes", "sector": "111", "monto": 1_000_000.0, "rho": 0.3}
    resp = client.post("/simulate", json=body)
    assert resp.status_code == 200
    payload = resp.get_json()

    from spatial.simulation.scenario import Scenario
    expected = Scenario(**{k: body[k] for k in ("estado", "sector", "monto", "rho")}).run(
        _state.modelo, _state.spatial_matrix,
    ).to_dict()

    assert payload["estado_key"] == expected["estado_key"]
    assert payload["mult_produccion"] == pytest.approx(expected["mult_produccion"])
    assert payload["delta_X_total_pesos"] == pytest.approx(expected["delta_X_total_pesos"])


# ══════════════════════════════════════════════════════════
# /decision-support/*
# ══════════════════════════════════════════════════════════
def test_decision_support_ageb_not_found(client):
    resp = client.get("/decision-support/ageb/0000000000000")
    assert resp.status_code == 404


def test_decision_support_ageb_real_id(client):
    warehouse_gdf = _state.warehouse_gdf
    cvegeo = str(warehouse_gdf["cvegeo"].iloc[0])
    resp = client.get(f"/decision-support/ageb/{cvegeo}")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ageb"] == cvegeo
    assert "cluster_id" in body
    assert "peso_total" in body


def test_decision_support_community_not_found(client):
    resp = client.get("/decision-support/community/999999")
    assert resp.status_code == 404


def test_decision_support_community_real_id(client):
    report = _state.decision_report()
    any_cluster_id = int(next(iter(report.community_profiles.keys())))
    resp = client.get(f"/decision-support/community/{any_cluster_id}")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["cluster_id"] == any_cluster_id


# ══════════════════════════════════════════════════════════
# Manejo de errores genérico
# ══════════════════════════════════════════════════════════
def test_unknown_route_returns_json_404(client):
    resp = client.get("/ruta-que-no-existe")
    assert resp.status_code == 404
    assert resp.get_json()["error"]
