# api/routes.py
"""
Stage 10 — Rutas de la API REST.

Cada endpoint es un envoltorio delgado sobre una API ya cerrada del
motor:

    GET  /health                                -> EngineState.readiness()
    GET  /catalog                                -> ModeloEconomico.mapa_estados / .sectores
    POST /simulate                               -> spatial.simulation.scenario.Scenario (Stage 8D, CERRADO)
    GET  /decision-support/ageb/<cvegeo>          -> spatial.decision_support (CERRADO)
    GET  /decision-support/community/<cluster_id> -> spatial.decision_support (CERRADO)

Ningún endpoint recalcula Warehouse, Spatial Graph, Louvain, SERIO ni
ninguna simulación por su cuenta — `/simulate` ejecuta exactamente el
mismo pipeline que ya corre `app/pages/1_Run_Simulation.py`
(`modelo.simular()` -> `run_simulation_engine()`, aquí vía el
orquestador de más alto nivel, `Scenario.run()`), y los endpoints de
`/decision-support/*` son lecturas puntuales de un
`DecisionSupportReport` ya construido por `EngineState.decision_report()`.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from spatial.simulation.scenario import Scenario, ScenarioConfigError

bp = Blueprint("api", __name__)


def _scoped_shock_ageb_path() -> Path:
    """Ruta temporal única por request (bugfix — ver docstring de
    `simulate()` para el detalle de la condición de carrera que esto
    corrige). `Scenario.run()` (spatial/, CERRADO) ya acepta
    `shock_ageb_output` como parámetro explícito; el bug estaba en que
    esta ruta no lo proveía y dependía del default compartido
    `SHOCK_AGEB_PARQUET` (`data/ssd/shock_ageb.parquet`)."""
    return Path(tempfile.gettempdir()) / f"lattise_api_shock_ageb_{uuid.uuid4().hex}.parquet"


def _engine_state():
    """Dependency injection: el `EngineState` vive en `current_app`,
    inyectado por `create_app()` — nunca se instancia uno nuevo aquí,
    para que un test pueda inyectar un `EngineState` propio apuntando a
    fixtures sin tocar ninguna ruta."""
    return current_app.config["ENGINE_STATE"]


def _error(message: str, status: int, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


# ══════════════════════════════════════════════════════════
# GET /health — nunca intenta regenerar un artefacto que falte
# ══════════════════════════════════════════════════════════
@bp.get("/health")
def health():
    state = _engine_state()
    readiness = state.readiness()
    ok = all(readiness.values())
    return jsonify({"status": "ok" if ok else "degraded", "artifacts": readiness}), 200 if ok else 503


# ══════════════════════════════════════════════════════════
# GET /catalog — estados y sectores disponibles (para construir /simulate)
# ══════════════════════════════════════════════════════════
@bp.get("/catalog")
def catalog():
    state = _engine_state()
    modelo = state.modelo
    estados = sorted(modelo.mapa_estados.keys())
    sectores = [
        {"scian": s, "nombre": modelo.sector_names[s]}
        for s in modelo.sectores
    ]
    return jsonify({"estados": estados, "sectores": sectores, "n_estados": len(estados), "n_sectores": len(sectores)})


# ══════════════════════════════════════════════════════════
# POST /simulate — envoltorio de Scenario (Stage 8D, CERRADO)
#
# Bugfix: `Scenario.run()` tiene como default `shock_ageb_output=
# SHOCK_AGEB_PARQUET`, el mismo artefacto compartido y versionado que
# usa el resto del motor (`data/ssd/shock_ageb.parquet`). Antes de este
# fix, esta ruta no sobreescribía ese parámetro, así que cada request
# a `/simulate` escribía sobre ese único archivo en disco. Con más de
# un worker/request concurrente (el caso normal en un despliegue real
# de Railway) esto es una condición de carrera genuina: dos
# simulaciones simultáneas pueden pisarse el resultado entre sí, o una
# puede leer el `shock_ageb.parquet` que acaba de escribir la otra.
# El fix usa una ruta temporal única por request (nunca el artefacto
# compartido) y la borra al terminar, éxito o error.
# ══════════════════════════════════════════════════════════
@bp.post("/simulate")
def simulate():
    body = request.get_json(silent=True) or {}
    faltantes = [k for k in ("estado", "sector", "monto", "rho") if k not in body]
    if faltantes:
        return _error(
            "Faltan campos obligatorios en el body JSON.", 400, campos_faltantes=faltantes,
            campos_esperados=["estado", "sector", "monto", "rho"],
        )

    state = _engine_state()
    if state.spatial_matrix is None:
        return _error(
            "SpatialMatrix (graph.gal, Stage 8A) no disponible — no se puede propagar el shock.", 503,
        )

    try:
        monto = float(body["monto"])
        rho = float(body["rho"])
    except (TypeError, ValueError):
        return _error("'monto' y 'rho' deben ser numéricos.", 400)

    scenario = Scenario(estado=str(body["estado"]), sector=str(body["sector"]), monto=monto, rho=rho)
    shock_path = _scoped_shock_ageb_path()
    try:
        result = scenario.run(state.modelo, state.spatial_matrix, shock_ageb_output=shock_path)
    except ScenarioConfigError as exc:
        return _error(str(exc), 400)
    finally:
        try:
            shock_path.unlink(missing_ok=True)
        except OSError:
            pass

    return jsonify(result.to_dict())


# ══════════════════════════════════════════════════════════
# GET /decision-support/ageb/<cvegeo>
# ══════════════════════════════════════════════════════════
@bp.get("/decision-support/ageb/<cvegeo>")
def decision_support_ageb(cvegeo: str):
    state = _engine_state()
    report = state.decision_report()
    if report is None:
        return _error("Decision Support Engine no disponible (falta warehouse.parquet o sector_cluster.json).", 503)
    profile = report.ageb(cvegeo)
    if profile is None:
        return _error(f"AGEB '{cvegeo}' no encontrado en el universo actual.", 404)
    return jsonify(profile)


# ══════════════════════════════════════════════════════════
# GET /decision-support/community/<cluster_id>
# ══════════════════════════════════════════════════════════
@bp.get("/decision-support/community/<int:cluster_id>")
def decision_support_community(cluster_id: int):
    state = _engine_state()
    report = state.decision_report()
    if report is None:
        return _error("Decision Support Engine no disponible (falta warehouse.parquet o sector_cluster.json).", 503)
    profile = report.community(cluster_id)
    if profile is None:
        return _error(f"Comunidad '{cluster_id}' no encontrada.", 404)
    return jsonify(profile)


__all__ = ["bp"]
