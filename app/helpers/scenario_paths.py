# app/helpers/scenario_paths.py
"""
Aislamiento de `shock_ageb.parquet` por ejecución (bugfix).

Contexto: `spatial.simulation.engine.run_simulation_engine()`,
`run_rho_sensitivity()` y `spatial.simulation.calibration.calibrate_rho()`
(todas Stage 7-8, CERRADAS) reciben `shock_ageb_output_path` como
parámetro opcional, pero su *default* apunta al artefacto compartido
`data/ssd/shock_ageb.parquet` (`spatial.config` -> `SHOCK_AGEB_PARQUET`).
Ese archivo está versionado en git.

Antes de este fix, `app/pages/1_Run_Simulation.py` llamaba a esas tres
funciones sin sobreescribir el parámetro, así que cada simulación
lanzada desde Lattise Studio (y cada corrida de
`tests/test_app_pages.py`, que ejecuta esta página con
`streamlit.testing.v1.AppTest`) escribía sobre el mismo archivo
versionado. En un despliegue con más de un usuario/worker concurrente
(Railway), esto es además una condición de carrera real: dos
simulaciones simultáneas se pisan el resultado entre sí.

Esto NO requiere ni justifica tocar `spatial/` (CERRADO) — las tres
funciones ya aceptan una ruta explícita; el bug estaba en que la capa
`app/` no la proveía. Este módulo centraliza la ruta única por
ejecución para que ningún call-site de la página vuelva a depender del
default compartido.
"""
from __future__ import annotations

import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def scoped_shock_ageb_path() -> Iterator[Path]:
    """
    Ruta temporal única (un archivo por invocación, nunca el artefacto
    compartido de `data/ssd/`). Se limpia al salir del bloque `with`,
    tanto en éxito como en excepción.

    Uso:
        with scoped_shock_ageb_path() as shock_path:
            gdf, report = run_simulation_engine(
                resultado_simulacion, rho, shock_ageb_output_path=shock_path,
            )
    """
    path = Path(tempfile.gettempdir()) / f"lattise_shock_ageb_{uuid.uuid4().hex}.parquet"
    try:
        yield path
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Best-effort: si el filesystem temporal es de solo lectura o
            # ya fue limpiado por el SO, no vale la pena tumbar la sesión
            # de Streamlit por esto.
            pass


__all__ = ["scoped_shock_ageb_path"]
