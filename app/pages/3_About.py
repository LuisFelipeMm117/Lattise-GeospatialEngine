# app/pages/3_About.py
"""
Lattise Studio -- About

Pagina informativa: que es el motor, que stages estan cerrados, y
metadatos vivos del repositorio (conteo de tests, ultimo commit). No
contiene logica economica ni espacial propia -- solo lee metadatos del
propio repo en disco (nunca inventa cifras: si no puede leer un dato,
lo omite en vez de mostrar un numero falso).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.components.styles import inject_styles  # noqa: E402

st.set_page_config(
    page_title="About - Lattise Studio",
    page_icon="\u25c6",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_styles()

# ======================================================================
# HEADER
# ======================================================================
st.markdown('<div class="kicker">\u25c6 ABOUT</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Lattise Geospatial Engine</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Motor espacial-economico que distribuye la actividad nacional '
    "(SERIO, 78 sectores) al nivel de AGEB y propaga shocks de demanda con un operador "
    "espacial -- mas la consola operativa que estas usando ahora mismo.</div>",
    unsafe_allow_html=True,
)
st.markdown('<hr class="thin">', unsafe_allow_html=True)


# ======================================================================
# METADATOS VIVOS DEL REPO -- nunca hardcodeados, siempre leidos en el
# momento. Si un dato no se puede obtener, se omite en vez de mostrar
# un numero que se vuelva falso con el tiempo (la leccion de por que
# esta pagina estuvo vacia: es mas facil dejarla en blanco que
# mantenerla al dia a mano -- asi que no se mantiene a mano).
# ======================================================================
def _run_git(*args: str):
    try:
        out = subprocess.run(
            ["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _count_tests():
    tests_dir = _REPO_ROOT / "tests"
    if not tests_dir.exists():
        return None
    total = 0
    for f in tests_dir.glob("test_*.py"):
        total += f.read_text(encoding="utf-8", errors="ignore").count("\ndef test_")
    return total


last_commit = _run_git("log", "-1", "--format=%h - %ad - %s", "--date=short")
n_tests = _count_tests()
n_test_files = len(list((_REPO_ROOT / "tests").glob("test_*.py"))) if (_REPO_ROOT / "tests").exists() else None

k1, k2, k3 = st.columns(3)
k1.metric("Tests en la suite", n_tests if n_tests is not None else "-")
k2.metric("Modulos de test", n_test_files if n_test_files is not None else "-")
k3.metric("Ultimo commit", last_commit.split(" - ")[0] if last_commit else "-")
if last_commit:
    st.caption(last_commit)

st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ======================================================================
# PIPELINE -- mismo estado que README.md, para que ambos no se
# desincronicen: si cambias uno, cambia el otro.
# ======================================================================
st.markdown("#### Pipeline -- SEW - SSD - SEE")
st.markdown(
    """
| Stage | Modulo | Estado |
|---|---|---|
| 1-2. Ingesta + Validacion AGEB | `warehouse/ageb_loader.py` | Cerrado |
| 3. Normalizacion (CRS, geometria) | `warehouse/ageb_loader.py::normalize()` | Cerrado |
| 3-4. DENUE + Crosswalk SCIAN->SERIO | `warehouse/denue_loader.py`, `warehouse/crosswalk.py` | Cerrado |
| 5. Warehouse (Spatial Join, omega) | `warehouse/builder.py` | Cerrado |
| 6. QA / Diagnostics | `analytics/diagnostics.py` | Cerrado |
| 7. Shock Allocation (SSD) | `allocation/allocator.py` | Cerrado |
| 8A. Spatial Graph (Matriz M) | `graph/network.py` | Cerrado |
| 8B-8D. Simulacion (SEE) | `simulation/` | Cerrado |
| 9. Visualizacion | `visualization/maps.py` | Cerrado |
| -- | Decision Support Engine | Cerrado |
| 10. API REST | -- | No presente en este repositorio |
"""
)

st.markdown('<hr class="thin">', unsafe_allow_html=True)
st.caption(
    "Lattise Studio no recalcula ninguna magnitud economica en esta pagina -- todo lo de "
    "arriba se lee de metadatos del repositorio o de la tabla de estado documentada en "
    "README.md, nunca se inventa ni se estima."
)
