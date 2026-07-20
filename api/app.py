# api/app.py
"""
Stage 10 — Flask app factory.

`create_app(engine_state=None)` es el único punto de entrada. Si no se
pasa un `EngineState`, se construye uno por defecto apuntando a los
artefactos reales del repo (mismas rutas que `spatial.config` y
`app/helpers/data_sources.py`). Los tests inyectan su propio
`EngineState` apuntando a fixtures — nunca parchan `spatial.config` ni
monkeypatchean imports.
"""
from __future__ import annotations

from flask import Flask, jsonify

from api.routes import bp
from api.state import EngineState


def create_app(engine_state: EngineState | None = None) -> Flask:
    app = Flask(__name__)
    app.config["ENGINE_STATE"] = engine_state or EngineState()
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_exc):
        return jsonify({"error": "Ruta no encontrada."}), 404

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return jsonify({"error": "Método no permitido para esta ruta."}), 405

    @app.errorhandler(500)
    def internal_error(_exc):
        return jsonify({"error": "Error interno del servidor."}), 500

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app().run(debug=True, port=5000)
