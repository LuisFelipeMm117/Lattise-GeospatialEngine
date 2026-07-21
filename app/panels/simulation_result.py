# app/panels/simulation_result.py
"""
Run Simulation -- panel de resultado completo.

Extraido de app/pages/1_Run_Simulation.py sin cambios de comportamiento.
Jerarquia: summary -> map -> kpi -> insights -> rank -> export. Todo
dato mostrado ya existia en `gdf` / `report` -- aqui solo se ordena,
formatea y agrupa visualmente.
"""
from __future__ import annotations

import io
import json

import streamlit as st

from spatial.config import AGEB_ID_COL
from spatial.simulation.engine import IMPACTO_PROPAGADO_COL

from app.components.simulation_map import (
    _VARIABLE_OPTIONS,
    render_detail_panel,
    render_map_block,
)
from app.helpers.formatting import md
from app.helpers.simulation_formatting import format_compact, format_money

def render_result(report, gdf, scenario: dict):
    sector_label = scenario.get("sector", "—")
    estado_label = scenario.get("estado", "—")
    rho_label = scenario.get("rho", 0.0)
    monto_label = scenario.get("monto_pesos", 0.0)

    mult_txt = (
        f"{report.multiplicador_global:.2f}×"
        if report.multiplicador_global is not None else "—"
    )

    # ── 1. Executive Summary (≤4 líneas) ─────────────────────────────
    md(f"""
    <div class="exec-summary">
    A <strong>{format_money(monto_label)}</strong> shock in <strong>{sector_label}</strong>
    ({estado_label}) propagates to <strong>{format_money(report.shock_total_propagado)}</strong>
    in spatial economic impact — a <strong>{mult_txt}</strong> multiplier — across the AGEB
    network at ρ = {rho_label:.2f}, computed in {report.tiempo_ejecucion_seg:.2f}s.
    </div>
    """)

    # ── 2. Spatial Map ────────────────────────────────────────────────
    st.markdown('<div class="section-label">Spatial Map</div>', unsafe_allow_html=True)
    gdf_map, value_col = render_map_block(gdf, sector_label)
    var_label = [k for k, v in _VARIABLE_OPTIONS.items() if v == value_col][0]

    # ── 2b. AGEB Detail Panel (map ↔ ranking, mismo selected_ageb_id) ──
    render_detail_panel(gdf_map, value_col, var_label)

    # ── 3. KPIs (discretos) ───────────────────────────────────────────
    n_agebs = len(gdf)
    n_afectadas = int((gdf[IMPACTO_PROPAGADO_COL].abs() > 0).sum())
    impacto_promedio = float(gdf[IMPACTO_PROPAGADO_COL].mean()) if n_agebs else 0.0
    impacto_maximo = float(gdf[IMPACTO_PROPAGADO_COL].max()) if n_agebs else 0.0

    md(f"""
    <div class="kpi-strip">
        <div class="kpi-item">
            <div class="kpi-label">Direct Impact</div>
            <div class="kpi-value">{format_money(report.shock_total_inicial)}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Spatial Impact</div>
            <div class="kpi-value accent">{format_money(report.shock_total_propagado)}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Multiplier</div>
            <div class="kpi-value">{mult_txt}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">AGEBs Affected</div>
            <div class="kpi-value">{n_afectadas:,} / {n_agebs:,}</div>
        </div>
        <div class="kpi-item">
            <div class="kpi-label">Runtime</div>
            <div class="kpi-value">{report.tiempo_ejecucion_seg:.2f}s</div>
        </div>
    </div>
    """)

    # ── 4. Spatial Insights ───────────────────────────────────────────
    st.markdown('<div class="section-label">Spatial Insights</div>', unsafe_allow_html=True)

    if gdf_map is not None and not gdf_map.empty:
        top10_share = float(
            gdf_map.sort_values(value_col, ascending=False).head(10)["participacion_pct"].sum()
        )
        top_row = gdf_map.sort_values(value_col, ascending=False).iloc[0]
        n_municipios = gdf_map["municipio"].nunique()

        md(f"""
        <div>
            <div class="insight-line"><span class="dot-sm"></span>
                Top 10 AGEBs concentrate <strong>{top10_share:.1f}%</strong> of total {var_label.lower()}.
            </div>
            <div class="insight-line"><span class="dot-sm"></span>
                Highest impact: AGEB <strong>{top_row[AGEB_ID_COL]}</strong>
                (municipio {top_row['municipio']}) with {format_money(top_row[value_col])}.
            </div>
            <div class="insight-line"><span class="dot-sm"></span>
                Effect spans <strong>{n_municipios}</strong> municipios across
                <strong>{n_afectadas:,}</strong> affected AGEBs.
            </div>
            <div class="insight-line"><span class="dot-sm"></span>
                Average impact per AGEB: <strong>{format_money(impacto_promedio)}</strong> ·
                Maximum: <strong>{format_money(impacto_maximo)}</strong>.
            </div>
        </div>
        """)
    else:
        st.caption("No geometry available to compute spatial insights.")

    # ── 5. Rankings (visual, no dataframe) ────────────────────────────
    st.markdown('<div class="section-label">Top 10 AGEBs</div>', unsafe_allow_html=True)

    if gdf_map is not None and not gdf_map.empty:
        df_rank = (
            gdf_map[[AGEB_ID_COL, "municipio", value_col]]
            .sort_values(value_col, ascending=False)
            .head(10)
            .reset_index(drop=True)
        )
        max_val = float(df_rank[value_col].abs().max()) or 1.0

        # NOTA: cada fila se arma como una sola línea, sin saltos ni
        # indentación. Un f-string HTML multilínea indentado dentro de un
        # loop es interpretado por Streamlit como bloque de código Markdown
        # (4+ espacios ⇒ ``` ) en vez de HTML, que es la causa del bug
        # reportado ("no renderiza, se ve el HTML crudo"). Concatenando en
        # una sola línea se evita el problema de raíz — sin tocar ningún
        # valor del motor.
        #
        # Cada fila vive en dos columnas: el HTML existente (barra + valor)
        # a la izquierda, y un botón real de Streamlit a la derecha que
        # asigna `selected_ageb_id` — mismo estado que ya consume el mapa
        # (highlight) y el panel de detalle, cerrando el loop de selección
        # mapa ↔ ranking ↔ detalle.
        selected_id = st.session_state.get("selected_ageb_id")
        for i, row in df_rank.iterrows():
            pct = min(100.0, abs(float(row[value_col])) / max_val * 100)
            row_id = str(row[AGEB_ID_COL])
            is_selected = row_id == str(selected_id) if selected_id else False
            row_html = (
                '<div class="rank-item">'
                f'<div class="rank-num">#{i + 1:02d}</div>'
                '<div class="rank-body">'
                '<div class="rank-name"><span>AGEB '
                f'{row[AGEB_ID_COL]} '
                f'<span class="rank-muni">· municipio {row["municipio"]}</span></span></div>'
                '<div class="rank-bar-track">'
                f'<div class="rank-bar-fill" style="width:{pct:.1f}%;"></div>'
                '</div>'
                '</div>'
                f'<div class="rank-value">{format_compact(row[value_col])}</div>'
                '</div>'
            )
            wrap_class = "rank-row-wrap selected" if is_selected else "rank-row-wrap"

            col_row, col_btn = st.columns([0.92, 0.08])
            with col_row:
                st.markdown(f'<div class="{wrap_class}">{row_html}</div>', unsafe_allow_html=True)
            with col_btn:
                st.markdown('<div class="rank-select-col">', unsafe_allow_html=True)
                if st.button(
                    "◉" if is_selected else "○",
                    key=f"rank_select_{row_id}",
                    help=f"Select AGEB {row_id} on the map",
                ):
                    st.session_state["selected_ageb_id"] = row_id
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.caption("No geometry available to build the ranking.")

    # ── 6. Export ──────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Export</div>', unsafe_allow_html=True)
    e1, e2, e3 = st.columns(3)

    with e1:
        try:
            geojson_bytes = gdf.to_json().encode("utf-8")
            st.download_button(
                "⬇ GeoJSON", data=geojson_bytes,
                file_name="lattise_simulation_result.geojson",
                mime="application/geo+json", use_container_width=True,
            )
        except Exception as e:
            st.button("⬇ GeoJSON", disabled=True, use_container_width=True)
            st.caption(f"Unavailable: {e}")

    with e2:
        try:
            buf = io.BytesIO()
            gdf.to_parquet(buf)
            st.download_button(
                "⬇ Parquet", data=buf.getvalue(),
                file_name="lattise_simulation_result.parquet",
                mime="application/octet-stream", use_container_width=True,
            )
        except Exception as e:
            st.button("⬇ Parquet", disabled=True, use_container_width=True)
            st.caption(f"Unavailable: {e}")

    with e3:
        report_json = json.dumps(report.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
        st.download_button(
            "⬇ JSON Report", data=report_json,
            file_name="lattise_simulation_report.json",
            mime="application/json", use_container_width=True,
        )


def render_empty_state():
    md("""
    <div class="exec-summary">
    Define a scenario in the toolbar above and press <strong>Launch</strong> to run the
    spatial propagation engine. Results — map, KPIs, insights, rankings and exports —
    will appear here once the simulation completes.
    </div>
    """)
    st.markdown('<div class="section-label">Spatial Map</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="map-placeholder">Spatial visualization will appear here once a '
        'simulation has been executed.</div>',
        unsafe_allow_html=True,
    )
