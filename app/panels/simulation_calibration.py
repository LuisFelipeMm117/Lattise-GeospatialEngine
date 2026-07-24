# app/panels/simulation_calibration.py
"""
Run Simulation -- panel de calibración de ρ (Moran's I).

Presenta `RhoCalibrationResult` (ya calculado por la página, EJECUCIÓN,
vía `spatial.simulation.calibration.calibrate_rho`) -- este módulo no
recalcula nada, solo formatea. El descargo metodológico se muestra
SIEMPRE, de forma prominente (no en un tooltip ni en letra chica) --
ver `spatial/simulation/calibration.py` para por qué esto importa.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from spatial.simulation.calibration import RhoCalibrationResult


def render_calibration_summary(result: RhoCalibrationResult, scenario: dict) -> None:
    st.markdown('<div class="section-label">Calibración de ρ — Moran\'s I</div>', unsafe_allow_html=True)

    st.warning(
        "**Esto NO es una estimación causal de ρ.** Es una calibración por "
        "momentos: se eligió el ρ cuyo patrón de propagación espacial es más "
        "consistente con el agrupamiento ya observado en la actividad "
        "económica real de esta región. Una estimación causal requiere datos "
        "de panel temporal, actualmente no disponibles "
        "(`spatial/allocation/simulation.py`). Usa este ρ como punto de "
        "partida razonable, no como un valor definitivo para una decisión "
        "de alto riesgo sin más validación.",
        icon="⚠️",
    )

    if not result.convergio:
        st.error(
            "La calibración no encontró ningún ρ válido en el rango evaluado "
            "para este escenario. Revisa si el sector elegido tiene cobertura "
            "espacial en el warehouse."
        )
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ρ calibrado", f"{result.rho_calibrado:.4f}")
    k2.metric("Moran's I observado", f"{result.morans_i_observado:.4f}", help="Actividad económica real (Stage 5)")
    k3.metric("Moran's I del modelo", f"{result.morans_i_modelo:.4f}", help="Shock propagado con el ρ calibrado")
    k4.metric("Diferencia", f"{result.diferencia_absoluta:.4f}")

    if not result.grid.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=result.grid["rho"], y=result.grid["morans_i_Y"],
            mode="markers", name="Moran's I del modelo por ρ",
            marker=dict(size=6, color="#7C9CFF"),
        ))
        fig.add_hline(
            y=result.morans_i_observado, line_dash="dot", line_color="#34D399",
            annotation_text="Moran's I observado (real)",
        )
        fig.add_vline(x=result.rho_calibrado, line_dash="dash", line_color="#F5B942")
        fig.update_layout(
            title="Búsqueda en grilla — Moran's I del modelo vs ρ",
            xaxis_title="ρ", yaxis_title="Moran's I",
            height=320, margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Criterio espacial: {result.criterio_espacial or '—'} · "
        f"{result.n_agebs} AGEB(s) · {result.n_rho_evaluados} valores de ρ evaluados en la grilla."
    )
