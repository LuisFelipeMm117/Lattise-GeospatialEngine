# api/__init__.py
"""
Stage 10 — API REST del Lattise Geospatial Engine.

Envoltorio Flask de solo lectura (+ un endpoint de acción, `/simulate`,
que ejecuta exactamente el mismo pipeline que ya corre
`app/pages/1_Run_Simulation.py`) sobre los stages cerrados del motor.
No reconstruye ni recalcula Warehouse, Spatial Graph, Louvain, SERIO ni
Decision Support — todo eso ya vive en `spatial/`, `serio/` y
`spatial/decision_support/`.

Uso:

    from api.app import create_app
    app = create_app()
    app.run(...)
"""
from api.app import create_app  # noqa: F401
from api.state import EngineState  # noqa: F401

__all__ = ["create_app", "EngineState"]
