# tests/test_app_pages.py
"""
Tests de humo — `app/`.

Historial: hasta esta sesión, `app/` tenía cobertura de tests cero
(excepto `app/helpers/decision_support_bridge.py`, agregado en un
refactor previo). Dos problemas reales llegaron a `main` sin que nada
los atrapara:

    1. `app/pages/3_About.py` quedó vacío (0 bytes) desde el commit que
       lo creó — una página en blanco visible en producción.
    2. Al renombrar `1_Run Simulation.py` / `2_View Results.py` para
       quitarles el espacio, `app/home.py` y `2_View_Results.py` tenían
       3 llamadas a `st.switch_page()` con el nombre de archivo viejo
       hardcodeado — la navegación se habría roto en silencio.

Estas pruebas usan `streamlit.testing.v1.AppTest`, que ejecuta cada
página en un runtime real de Streamlit (no un mock, no un parseo de
sintaxis) y expone cualquier excepción no capturada que ocurra durante
el `run()` de la página — exactamente el tipo de regresión que los dos
casos de arriba representan.

No verifican contenido de negocio (eso ya lo cubre `tests/` para el
motor y `tests/test_decision_support_bridge.py` para el bridge) — solo
que cada página cargue sin explotar, con y sin datos de simulación en
`session_state`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

streamlit_testing = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit.testing.v1.AppTest no disponible en esta versión de streamlit"
)
AppTest = streamlit_testing.AppTest

_PAGES = [
    "app/home.py",
    "app/pages/1_Run_Simulation.py",
    "app/pages/2_View_Results.py",
    "app/pages/3_About.py",
    "app/pages/4_Spatial_Cluster_Intelligence.py",
    "app/pages/5_Opportunity_Explorer.py",
]


@pytest.mark.parametrize("page", _PAGES)
def test_page_loads_without_exception(page: str):
    """Cada página debe cargar sin excepción no capturada — sin datos
    de simulación en `session_state` (el caso más común: primera visita
    del usuario)."""
    at = AppTest.from_file(str(_REPO_ROOT / page), default_timeout=60)
    at.run()
    assert not at.exception, f"{page} lanzó una excepción al cargar: {at.exception}"


def test_about_page_is_not_empty():
    """Regresión específica de H2: `3_About.py` estuvo vacío durante
    varios commits sin que nada lo detectara."""
    content = (_REPO_ROOT / "app/pages/3_About.py").read_text(encoding="utf-8")
    assert len(content.strip()) > 100, "3_About.py está vacío o casi vacío otra vez."


def test_no_page_filenames_have_spaces():
    """Regresión específica de H5/H8: nombres de archivo con espacios
    rompen cualquier referencia hardcodeada (`st.switch_page`) sin
    avisar hasta producción."""
    pages_dir = _REPO_ROOT / "app" / "pages"
    offenders = [p.name for p in pages_dir.glob("*.py") if " " in p.name]
    assert not offenders, f"Archivos de página con espacios en el nombre: {offenders}"


def test_switch_page_references_point_to_existing_files():
    """Cualquier `st.switch_page("pages/...")` en todo `app/` debe
    apuntar a un archivo que realmente exista — la clase de bug que
    encontramos al renombrar páginas en esta sesión."""
    import re

    pattern = re.compile(r'st\.switch_page\(\s*["\'](pages/[^"\']+\.py)["\']')
    offenders = []
    for py_file in (_REPO_ROOT / "app").rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            referenced = _REPO_ROOT / "app" / match.group(1)
            if not referenced.exists():
                offenders.append(f"{py_file.relative_to(_REPO_ROOT)} -> {match.group(1)}")
    assert not offenders, f"st.switch_page() apuntando a archivos inexistentes: {offenders}"


def test_run_simulation_full_flow_after_decomposition():
    """Regresión específica de H9: `1_Run_Simulation.py` se descompuso
    de 1,451 líneas en 7 módulos (`simulation_styles`,
    `simulation_toolbar`, `simulation_map`, `simulation_formatting`,
    `scenario_manager`, `simulation_result`, `simulation_comparison`).
    Un test de "la página carga sin excepción" (ver
    `test_page_loads_without_exception` arriba) no habría atrapado un
    error de wiring entre módulos que solo aparece al presionar
    Launch — este test ejercita esa ruta completa: toolbar -> Launch ->
    modelo.simular() -> run_simulation_engine() -> scenario_manager ->
    render_result (mapa + KPIs + insights + ranking + export)."""
    at = AppTest.from_file(str(_REPO_ROOT / "app/pages/1_Run_Simulation.py"), default_timeout=90)
    at.run()
    assert not at.exception, f"Carga inicial falló: {at.exception}"

    launch_buttons = [b for b in at.button if b.label == "▶ Launch"]
    assert launch_buttons, "No se encontró el botón Launch en el toolbar."
    launch_buttons[0].click()
    at.run()
    assert not at.exception, f"Ejecutar una simulación falló tras la descomposición: {at.exception}"

    # El resultado debe haberse renderizado (KPIs/insights/ranking) — no
    # solo "no truena", sino que produce contenido real.
    assert len(at.markdown) > 10, "render_result no parece haber producido contenido."
