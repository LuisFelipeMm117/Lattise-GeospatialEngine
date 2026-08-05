"""Panel de lectura y descarga del expediente educativo de una simulación."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from spatial.simulation.educational_report import build_educational_report_from_engine_result


def _cached_report(gdf, simulation_report, scenario: dict):
    scenario_id = st.session_state.get("active_scenario_id", "current")
    cache_key = f"educational_report::{scenario_id}"
    cached = st.session_state.get(cache_key)
    if cached is None:
        cached = build_educational_report_from_engine_result(gdf, simulation_report, scenario)
        st.session_state[cache_key] = cached
    return cached


def render_educational_report(gdf, simulation_report, scenario: dict) -> None:
    """Muestra el reporte ya derivado de resultados existentes, sin recálculo."""
    educational = _cached_report(gdf, simulation_report, scenario)
    coverage = educational.spatial_coverage
    summary = educational.summary

    st.markdown('<div class="section-label">Educational Report</div>', unsafe_allow_html=True)
    with st.expander("Open reproducible educational report", expanded=True):
        st.caption(
            f"ID {educational.report_id} · generado {educational.generated_at_utc} · "
            f"motor {educational.engine['version']}"
        )
        st.warning(educational.methodological_warning)

        m1, m2, m3 = st.columns(3)
        m1.metric("AGEBs with impact", f"{coverage['pct_agebs_con_impacto']:.1f}%")
        m2.metric("AGEBs with direct shock", coverage["n_agebs_con_shock_directo"])
        mult = summary["multiplicador_espacial_global"]
        m3.metric("Spatial multiplier", f"{mult:.4f}" if mult is not None else "—")

        st.markdown("**Data provenance**")
        provenance_rows = []
        for name, value in educational.artifacts.items():
            if name == "bundle":
                provenance_rows.append({"artifact": "bundle", "version": value["status"], "sha256": value["sha256"] or "not configured"})
                continue
            primary = value.get("dataset") or value.get("gal") or value.get("meta", {})
            provenance_rows.append({
                "artifact": name,
                "version": value.get("version", primary.get("version", "unversioned")),
                "sha256": primary.get("sha256") or "unavailable",
            })
        st.dataframe(pd.DataFrame(provenance_rows), use_container_width=True, hide_index=True)

        excluded = coverage["sectores_excluidos"]
        if excluded:
            st.info("Sectores excluidos por falta de cobertura espacial: " + ", ".join(map(str, excluded)))

        st.markdown("**Top AGEBs by propagated impact**")
        ranking = pd.DataFrame(educational.ranking).rename(columns={
            "rango": "Rank", "cvegeo": "AGEB", "shock_directo": "Direct",
            "impacto_propagado": "Propagated", "impacto_indirecto": "Indirect",
        })
        st.dataframe(
            ranking.style.format({"Direct": "{:,.2f}", "Propagated": "{:,.2f}", "Indirect": "{:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

        payload = json.dumps(educational.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "Download educational report (JSON)",
            data=payload,
            file_name=f"lattise_educational_report_{educational.report_id}.json",
            mime="application/json",
            use_container_width=True,
        )
