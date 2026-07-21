# app/helpers/scenario_manager.py
"""
Run Simulation -- Scenario Manager (Fase 2).

Extraido de app/pages/1_Run_Simulation.py sin cambios de comportamiento
(solo se quito el guion bajo inicial de las funciones, ya que ahora
cruzan un limite de modulo, y `_md` -> `md` compartido).

Orquestacion de estado pura. Cada entrada de historial envuelve un
(gdf, report) ya producidos por `modelo.simular()` +
`run_simulation_engine()`; nunca se recalcula ni deriva economia nueva
aqui, solo se guardan/activan punteros.
"""
from __future__ import annotations

import time
import uuid

import streamlit as st

from app.helpers.formatting import md
from app.helpers.simulation_formatting import format_compact

MAX_SCENARIO_HISTORY = 8


def scenario_label(scenario: dict) -> str:
    """Etiqueta compacta para un chip de historial. Presentación pura."""
    sector_short = str(scenario.get("sector", "—"))[:20]
    monto = scenario.get("monto_pesos", 0.0)
    sign = "+" if monto >= 0 else ""
    rho_val = scenario.get("rho", 0.0)
    return (
        f"{scenario.get('estado', '—')} · {sector_short} · "
        f"{sign}{format_compact(monto)} · ρ{rho_val:.2f}"
    )


def new_history_entry(scenario: dict, gdf, report) -> dict:
    """Empaqueta un resultado ya calculado (gdf, report) como entrada de
    historial. No transforma ni recalcula ningún valor del motor."""
    return {
        "id": uuid.uuid4().hex[:8],
        "label": scenario_label(scenario),
        "scenario": scenario,
        "gdf": gdf,
        "report": report,
        "timestamp": time.time(),
    }


def activate_entry(entry: dict) -> None:
    """Apunta el estado activo (mismas claves que consumen las páginas
    2_View_Results.py y 4_Spatial_Cluster_Intelligence.py) hacia una
    entrada del historial ya calculada. Cero recálculo."""
    st.session_state["active_scenario_id"] = entry["id"]
    st.session_state["simulation_scenario"] = entry["scenario"]
    st.session_state["simulation_gdf"] = entry["gdf"]
    st.session_state["simulation_report"] = entry["report"]
    st.session_state["simulation_timestamp"] = entry["timestamp"]
    st.session_state["selected_ageb_id"] = None


def render_scenario_manager() -> None:
    """Tira de chips con los últimos escenarios ya ejecutados en esta
    sesión. Permite reactivar (sin recomputar) o descartar un escenario, y
    marcar hasta 2 para el modo de Comparación (Fase 3)."""
    history = st.session_state.get("scenario_history", [])
    if not history:
        return

    valid_ids = {e["id"] for e in history}
    st.session_state["compare_selection"] = [
        cid for cid in st.session_state.get("compare_selection", []) if cid in valid_ids
    ]

    st.markdown('<div class="section-label">Scenario History</div>', unsafe_allow_html=True)
    st.markdown('<div class="scenario-manager-wrap">', unsafe_allow_html=True)

    active_id = st.session_state.get("active_scenario_id")
    compare_sel = st.session_state["compare_selection"]
    for entry in history:
        is_active = entry["id"] == active_id
        wrap_class = "scenario-chip active" if is_active else "scenario-chip"
        c_cmp, c_label, c_go, c_del = st.columns([0.08, 0.70, 0.11, 0.11])
        with c_cmp:
            was_checked = entry["id"] in compare_sel
            checked = st.checkbox(
                "Compare", key=f"cmp_chk_{entry['id']}", value=was_checked,
                label_visibility="collapsed", help="Select for comparison (max 2)",
            )
            if checked and not was_checked:
                if len(compare_sel) >= 2:
                    compare_sel.pop(0)
                compare_sel.append(entry["id"])
            elif not checked and was_checked:
                compare_sel.remove(entry["id"])
        with c_label:
            marker = "●" if is_active else "○"
            md(f"""
            <div class="{wrap_class}"><span class="sc-dot">{marker}</span>
            <span class="sc-text">{entry['label']}</span></div>
            """)
        with c_go:
            if st.button(
                "View", key=f"activate_{entry['id']}",
                disabled=is_active, use_container_width=True,
            ):
                st.session_state["compare_mode"] = False
                activate_entry(entry)
                st.rerun()
        with c_del:
            if st.button(
                "✕", key=f"delete_{entry['id']}", use_container_width=True,
                help="Discard this scenario",
            ):
                st.session_state["scenario_history"] = [
                    e for e in history if e["id"] != entry["id"]
                ]
                if entry["id"] in st.session_state["compare_selection"]:
                    st.session_state["compare_selection"].remove(entry["id"])
                if is_active:
                    remaining = st.session_state["scenario_history"]
                    if remaining:
                        activate_entry(remaining[0])
                    else:
                        for k in (
                            "active_scenario_id", "simulation_scenario",
                            "simulation_gdf", "simulation_report",
                            "simulation_timestamp", "selected_ageb_id",
                        ):
                            st.session_state.pop(k, None)
                st.rerun()

    st.session_state["compare_selection"] = compare_sel
    n_sel = len(compare_sel)
    c_info, c_btn = st.columns([0.8, 0.2])
    with c_info:
        st.caption(f"{n_sel}/2 scenarios selected for comparison.")
    with c_btn:
        if st.button(
            "⇄ Compare", key="btn_open_compare", use_container_width=True,
            disabled=n_sel != 2, type="primary" if n_sel == 2 else "secondary",
        ):
            st.session_state["compare_mode"] = True
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
