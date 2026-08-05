# app/pages/1_Run_Simulation.py
"""
Lattise Studio — Run Simulation
Orquesta exclusivamente las APIs públicas ya cerradas del motor:
    serio.loader.ModeloEconomico.simular()
    spatial.simulation.engine.run_simulation_engine()
No recalcula Warehouse, Graph, SEE ni SERIO. No contiene lógica económica.

Refactor de descomposición (H9): esta página era un monolito de 1,451
líneas mezclando CSS, orquestación de session_state (Scenario Manager),
toolbar, mapa y render de resultado en un solo archivo — el mismo
defecto estructural ya identificado y corregido en
`5_Opportunity_Explorer.py`. Se descompuso siguiendo exactamente ese
patrón (`helpers/` + `components/` + `panels/`), sin cambiar ningún
comportamiento: cada bloque se movió tal cual a su módulo, verificado
con `streamlit.testing.v1.AppTest` antes y después del refactor.

    app/components/simulation_styles.py   — CSS (lenguaje visual GIS)
    app/components/simulation_toolbar.py  — definición de escenario (Fases 4-5)
    app/components/simulation_map.py      — mapa + panel de detalle
    app/helpers/simulation_formatting.py  — format_money/format_compact
    app/helpers/scenario_manager.py       — historial de escenarios (Fase 2)
    app/panels/simulation_result.py       — resultado completo (Fase 1)
    app/panels/simulation_comparison.py   — comparación lado a lado (Fase 3)
    app/panels/simulation_sensitivity.py  — barrido de ρ (Fase 5)

Esta página es ahora solo el "conductor": carga el modelo, dispara la
simulación (simple, compuesta o barrido de sensibilidad) cuando se
presiona Launch, y decide cuál de los cuatro estados (comparación /
sensibilidad / resultado / vacío) renderizar. Ninguna magnitud
económica se calcula aquí.
"""
import sys
from pathlib import Path

import streamlit as st

# ── Resolución de rutas del repo (app/pages/ → app/ → repo root) ───────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from serio.loader import ModeloEconomico  # noqa: E402
from spatial.simulation.calibration import calibrate_rho  # noqa: E402
from spatial.simulation.engine import run_rho_sensitivity, run_simulation_engine  # noqa: E402

from app.components.simulation_styles import inject_simulation_styles  # noqa: E402
from app.components.simulation_toolbar import render_toolbar  # noqa: E402
from app.helpers.scenario_manager import (  # noqa: E402
    MAX_SCENARIO_HISTORY,
    activate_entry,
    new_history_entry,
    render_scenario_manager,
)
from app.helpers.scenario_paths import scoped_shock_ageb_path  # noqa: E402
from app.helpers.auth_gate import render_logout_button, require_auth  # noqa: E402
from app.panels.simulation_calibration import render_calibration_summary  # noqa: E402
from app.panels.simulation_comparison import render_compare_view  # noqa: E402
from app.panels.simulation_result import render_empty_state, render_result  # noqa: E402
from app.panels.simulation_sensitivity import render_sensitivity  # noqa: E402

st.set_page_config(
    page_title="Run Simulation — Lattise Studio",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)
require_auth()
render_logout_button()
inject_simulation_styles()


# ══════════════════════════════════════════════════════════
# CARGA DEL MODELO (API pública existente — sin recálculo)
# ══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="Loading economic model…")
def cargar_modelo() -> ModeloEconomico:
    return ModeloEconomico(str(_REPO_ROOT / "serio" / "data"))

modelo = cargar_modelo()

_has_result = "simulation_report" in st.session_state and "simulation_gdf" in st.session_state

if "selected_ageb_id" not in st.session_state:
    st.session_state["selected_ageb_id"] = None
if "scenario_history" not in st.session_state:
    st.session_state["scenario_history"] = []
if "active_scenario_id" not in st.session_state:
    st.session_state["active_scenario_id"] = None
if "compare_selection" not in st.session_state:
    st.session_state["compare_selection"] = []
if "compare_mode" not in st.session_state:
    st.session_state["compare_mode"] = False
if "last_run_mode" not in st.session_state:
    st.session_state["last_run_mode"] = None

# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
status_label = "Ready" if not _has_result else "Result loaded"
st.markdown(
    f'<div class="pipeline-chip"><span class="dot"></span>'
    f'SERIO · Spatial Propagation · {status_label}</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="kicker">◆ SPATIAL SIMULATION</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Run Simulation</div>', unsafe_allow_html=True)
st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# TOOLBAR — definición de escenario (GIS command bar)
# ══════════════════════════════════════════════════════════
toolbar = render_toolbar(modelo)
estado_nombre = toolbar["estado_nombre"]
estado_key = toolbar["estado_key"]
shocks = toolbar["shocks"]
sector_name = toolbar["sector_name"]
monto_pesos = toolbar["monto_pesos"]
rho = toolbar["rho"]
modo_sensibilidad = toolbar["modo_sensibilidad"]
modo_calibrar = toolbar["modo_calibrar"]
rho_values = toolbar["rho_values"]
launch = toolbar["launch"]

# ══════════════════════════════════════════════════════════
# EJECUCIÓN — API pública existente, sin recálculo de etapas.
# Fase 2: cada corrida se empaqueta como entrada de scenario_history y
# se activa; el render de abajo lee SIEMPRE desde el puntero activo
# (mismas claves de session_state que ya consumen 2_View_Results.py y
# 4_Spatial_Cluster_Intelligence.py) — fuente de verdad única.
# ══════════════════════════════════════════════════════════
if launch:
    st.session_state["selected_ageb_id"] = None

    if modo_sensibilidad:
        with st.spinner(f"Corriendo barrido de sensibilidad ({len(rho_values)} valores de ρ)…"):
            try:
                # simular_multiple() se corre UNA vez (no depende de ρ);
                # run_rho_sensitivity() reutiliza esa S para cada ρ del
                # barrido, sin recalcular Stage 7 por cada uno.
                resultado_simulacion = modelo.simular_multiple(estado_key, shocks)
                # Bugfix: shock_ageb_output_path aislado (ver
                # app/helpers/scenario_paths.py) — nunca el default
                # compartido data/ssd/shock_ageb.parquet.
                with scoped_shock_ageb_path() as shock_path:
                    df_sensibilidad, meta_sensibilidad = run_rho_sensitivity(
                        resultado_simulacion, rho_values, shock_ageb_output_path=shock_path,
                    )
            except Exception as e:
                st.error(f"Sensitivity sweep failed: {e}")
            else:
                st.session_state["sensitivity_df"] = df_sensibilidad
                st.session_state["sensitivity_meta"] = meta_sensibilidad
                st.session_state["sensitivity_scenario"] = {
                    "estado": estado_nombre, "estado_key": estado_key,
                    "sector": sector_name, "shocks": shocks, "monto_pesos": monto_pesos,
                }
                st.session_state["last_run_mode"] = "sensitivity"

    elif modo_calibrar:
        with st.spinner("Calibrando ρ (Moran's I) y corriendo la simulación…"):
            try:
                resultado_simulacion = modelo.simular_multiple(estado_key, shocks)
                # Bugfix: cada llamada usa su propia ruta aislada de
                # shock_ageb.parquet (ver app/helpers/scenario_paths.py) —
                # nunca el default compartido data/ssd/shock_ageb.parquet.
                with scoped_shock_ageb_path() as shock_path_calib:
                    calibration_result = calibrate_rho(
                        resultado_simulacion, shock_ageb_output_path=shock_path_calib,
                    )
                # Nota de eficiencia (no de corrección): calibrate_rho() ya
                # corrió Stage 7 internamente para buscar el ρ; esta segunda
                # llamada a run_simulation_engine() vuelve a correr Stage 7
                # para ensamblar el GeoDataFrame final con ese ρ. Es
                # redundante pero barato (mismo patrón que ya existe entre
                # run_simulation_engine() y run_rho_sensitivity() —
                # funciones independientes, cada una corre su propio
                # Stage 7). No vale la pena fusionarlas por ahora.
                with scoped_shock_ageb_path() as shock_path:
                    gdf_final, report = run_simulation_engine(
                        resultado_simulacion, calibration_result.rho_calibrado,
                        shock_ageb_output_path=shock_path,
                    )
            except Exception as e:
                st.error(f"Calibration failed: {e}")
            else:
                scenario_dict = {
                    "estado": estado_nombre,
                    "estado_key": estado_key,
                    "sector": sector_name,
                    "shocks": shocks,
                    "shocks_detalle": resultado_simulacion.get("shocks_detalle", []),
                    "monto_pesos": monto_pesos,
                    "rho": calibration_result.rho_calibrado,
                    "rho_calibrado": True,
                }
                entry = new_history_entry(scenario_dict, gdf_final, report)
                history = st.session_state.setdefault("scenario_history", [])
                history.insert(0, entry)
                del history[MAX_SCENARIO_HISTORY:]
                activate_entry(entry)
                st.session_state["calibration_result"] = calibration_result
                st.session_state["last_run_mode"] = "calibrated"

    else:
        with st.spinner("Running simulation…"):
            try:
                # simular_multiple() generaliza simular() a N sectores; con 1
                # solo sector da un resultado idéntico (ver
                # tests/test_simular_multiple.py::test_single_sector_matches_simular_exactly).
                resultado_simulacion = modelo.simular_multiple(estado_key, shocks)
                # Bugfix: shock_ageb_output_path aislado (ver
                # app/helpers/scenario_paths.py) — nunca el default
                # compartido data/ssd/shock_ageb.parquet.
                with scoped_shock_ageb_path() as shock_path:
                    gdf_final, report = run_simulation_engine(
                        resultado_simulacion, rho, shock_ageb_output_path=shock_path,
                    )
            except Exception as e:
                st.error(f"Simulation failed: {e}")
            else:
                scenario_dict = {
                    "estado": estado_nombre,
                    "estado_key": estado_key,
                    "sector": sector_name,
                    "shocks": shocks,
                    "shocks_detalle": resultado_simulacion.get("shocks_detalle", []),
                    "monto_pesos": monto_pesos,
                    "rho": rho,
                }
                entry = new_history_entry(scenario_dict, gdf_final, report)
                history = st.session_state.setdefault("scenario_history", [])
                history.insert(0, entry)
                del history[MAX_SCENARIO_HISTORY:]
                activate_entry(entry)
                st.session_state["last_run_mode"] = "single"

render_scenario_manager()

_history_by_id = {e["id"]: e for e in st.session_state.get("scenario_history", [])}
_compare_ids = st.session_state.get("compare_selection", [])
_compare_ready = (
    st.session_state.get("compare_mode")
    and len(_compare_ids) == 2
    and all(cid in _history_by_id for cid in _compare_ids)
)

if _compare_ready:
    render_compare_view(_history_by_id[_compare_ids[0]], _history_by_id[_compare_ids[1]])
elif st.session_state.get("last_run_mode") == "sensitivity" and "sensitivity_df" in st.session_state:
    render_sensitivity(
        st.session_state["sensitivity_df"],
        st.session_state["sensitivity_meta"],
        st.session_state.get("sensitivity_scenario", {}),
    )
else:
    st.session_state["compare_mode"] = False
    _has_result = "simulation_report" in st.session_state and "simulation_gdf" in st.session_state
    if st.session_state.get("last_run_mode") == "calibrated" and "calibration_result" in st.session_state:
        render_calibration_summary(
            st.session_state["calibration_result"],
            st.session_state.get("simulation_scenario", {}),
        )
        st.markdown('<hr class="thin">', unsafe_allow_html=True)
    if _has_result:
        render_result(
            st.session_state["simulation_report"],
            st.session_state["simulation_gdf"],
            st.session_state.get("simulation_scenario", {}),
        )
    else:
        render_empty_state()
