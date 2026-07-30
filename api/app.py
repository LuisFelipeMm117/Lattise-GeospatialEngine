# api/app.py
"""
Stage 10 — Flask app factory.

`create_app(engine_state=None)` es el único punto de entrada. Si no se
pasa un `EngineState`, se construye uno por defecto apuntando a los
artefactos reales del repo (mismas rutas que `spatial.config` y
`app/helpers/data_sources.py`). Los tests inyectan su propio
`EngineState` apuntando a fixtures — nunca parchan `spatial.config` ni
monkeypatchean imports.

Preparación para distribución online (bugfix + hardening, ver
memoria/roadmap de migración a Railway + Next.js):

    1. CORS: si el frontend vive en otro dominio (Next.js en Vercel
       llamando a esta API en Railway), el navegador bloquea la
       petición sin cabeceras CORS explícitas. Orígenes configurables
       vía `ALLOWED_ORIGINS` (coma-separado); si no se define, CORS
       queda deshabilitado (comportamiento actual, sin regresión para
       desarrollo local/tests).
    2. `debug=True` en el servidor de desarrollo de Flask expone el
       debugger interactivo de Werkzeug — ejecución de código arbitrario
       si algo revienta. Nunca debe usarse en producción. El bloque
       `__main__` ahora solo sirve para desarrollo local explícito
       (`FLASK_DEBUG=1 python -m api.app`); el proceso real en
       producción lo levanta gunicorn (ver `Procfile`), que nunca pasa
       por esta rama.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify

from api.routes import bp
from api.state import EngineState


def create_app(engine_state: EngineState | None = None) -> Flask:
    app = Flask(__name__)
    app.config["ENGINE_STATE"] = engine_state or EngineState()
    app.register_blueprint(bp)

    allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if allowed_origins:
        from flask_cors import CORS

        origins = [o.strip() for o in allowed_origins.split(",") if o.strip()]
        CORS(app, resources={r"/*": {"origins": origins}})

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
    # Solo para desarrollo local. En producción, gunicorn importa
    # `create_app()` directamente (ver Procfile) y nunca ejecuta este
    # bloque.
    debug_mode = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    create_app().run(debug=debug_mode, port=int(os.environ.get("PORT", 5000)))
