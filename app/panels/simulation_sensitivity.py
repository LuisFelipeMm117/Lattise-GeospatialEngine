# app/panels/simulation_sensitivity.py
"""
Run Simulation -- panel de sensibilidad (Fase 5, GIS Workstation).

Presenta el resultado de `spatial.simulation.engine.run_rho_sensitivity`
(ya calculado por la página, EJECUCIÓN) -- este módulo no recalcula
nada, solo grafica y formatea `df_sensibilidad`/`meta`.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.helpers.formatting import md
from app.helpers.simulation_formatting import format_compact, format_money


def render_sensitivity(df_sensibilidad: pd.DataFrame, meta: dict, scenario: dict) -> None:
    sector_label = scenario.get("sector", "—")
    estado_label = scenario.get("estado", "—")
    monto_label = scenario.get("monto_pesos", 0.0)

    md(f"""
    <div class="exec-summary">
    Análisis de sensibilidad para un shock de <strong>{format_money(monto_label)}</strong>
    en <strong>{sector_label}</strong> ({estado_label}) — {len(df_sensibilidad)} valores de ρ
    evaluados, criterio espacial: {meta.get('criterio', '—')}.
    </div>
    """)
    st.markdown('<div class="section-label">Sensibilidad ρ</div>', unsafe_allow_html=True)

    if df_sensibilidad.empty:
        st.error(
            "Ningún valor de ρ del barrido fue válido para esta matriz espacial. "
            f"Rango efectivo admitido: (-{meta.get('rho_max_efectivo', 1):.4f}, "
            f"{meta.get('rho_max_efectivo', 1):.4f})."
        )
        return

    if meta.get("n_rho_invalidos", 0) > 0:
        rhos_invalidos = ", ".join(f"{e['rho']:.2f}" for e in meta["errores"])
        st.warning(
            f"{meta['n_rho_invalidos']} valor(es) de ρ quedaron fuera del rango válido "
            f"y se omitieron del barrido: {rhos_invalidos}."
        )

    if df_sensibilidad["multiplicador_global"].isna().all():
        st.error(
            "El shock total (ΣS) de este escenario es 0 en todos los AGEB de la matriz "
            "espacial — el sector elegido no tiene cobertura espacial en el warehouse "
            "(ver Allocation Report). El multiplicador no está definido para ningún ρ "
            "del barrido; prueba con otro sector."
        )
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ρ evaluados", len(df_sensibilidad))
    mult_min = df_sensibilidad["multiplicador_global"].min()
    mult_max = df_sensibilidad["multiplicador_global"].max()
    k2.metric("Multiplicador mínimo", f"{mult_min:.4f}" if pd.notna(mult_min) else "—")
    k3.metric("Multiplicador máximo", f"{mult_max:.4f}" if pd.notna(mult_max) else "—")
    rango_mult = (mult_max - mult_min) if pd.notna(mult_max) and pd.notna(mult_min) else 0.0
    k4.metric("Rango del multiplicador", f"{rango_mult:.4f}" if pd.notna(mult_max) else "—")

    col_a, col_b = st.columns(2)
    with col_a:
        fig_mult = px.line(
            df_sensibilidad, x="rho", y="multiplicador_global", markers=True,
            title="Multiplicador global vs ρ",
            labels={"rho": "ρ (decaimiento espacial)", "multiplicador_global": "Multiplicador (ΣY / ΣS)"},
        )
        fig_mult.update_traces(line_color="#7C9CFF", marker=dict(size=8))
        fig_mult.update_layout(height=360, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_mult, use_container_width=True)

    with col_b:
        fig_y = go.Figure()
        fig_y.add_trace(go.Scatter(
            x=df_sensibilidad["rho"], y=df_sensibilidad["suma_Y"],
            mode="lines+markers", name="ΣY (propagado)", line=dict(color="#34D399"),
        ))
        fig_y.add_hline(
            y=df_sensibilidad["suma_S"].iloc[0], line_dash="dot", line_color="#576073",
            annotation_text="ΣS (shock inicial)",
        )
        fig_y.update_layout(
            title="Impacto total propagado (ΣY) vs ρ",
            xaxis_title="ρ (decaimiento espacial)", yaxis_title="ΣY (MXN)",
            height=360, margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_y, use_container_width=True)

    interpretacion = (
        "El resultado es **poco sensible** a ρ en este rango — el multiplicador "
        "casi no cambia."
        if rango_mult < 0.15 else
        "El resultado es **moderadamente sensible** a ρ — vale la pena documentar "
        "qué valor de ρ se usó y por qué."
        if rango_mult < 0.5 else
        "El resultado es **muy sensible** a ρ — la elección de este parámetro "
        "cambia sustancialmente la conclusión del escenario. Considera acotar ρ con "
        "evidencia (SEE-Estimación) antes de usar esto para una decisión real."
    )
    st.info(interpretacion)

    with st.expander("📋 Tabla completa del barrido"):
        df_show = df_sensibilidad.copy()
        df_show["suma_S"] = df_show["suma_S"].apply(format_money)
        df_show["suma_Y"] = df_show["suma_Y"].apply(format_money)
        df_show["multiplicador_global"] = df_show["multiplicador_global"].apply(
            lambda v: f"{v:.4f}" if pd.notna(v) else "—"
        )
        df_show["condicion_I_menos_rhoW"] = df_show["condicion_I_menos_rhoW"].apply(format_compact)
        df_show = df_show.rename(columns={
            "rho": "ρ", "suma_S": "ΣS (shock inicial)", "suma_Y": "ΣY (propagado)",
            "multiplicador_global": "Multiplicador", "condicion_I_menos_rhoW": "cond(I − ρW)",
        })
        st.dataframe(df_show, use_container_width=True, hide_index=True)
        csv = df_sensibilidad.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Descargar CSV del barrido", csv, "sensibilidad_rho.csv", "text/csv")

    st.caption(
        f"Radio espectral(W) = {meta.get('radio_espectral_W', 0):.6f} · "
        f"ρ máximo efectivo admitido para esta matriz = "
        f"{meta.get('rho_max_efectivo', float('inf')):.4f} · {meta.get('n_agebs', 0)} AGEB(s)."
    )
