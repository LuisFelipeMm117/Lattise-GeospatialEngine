# app/components/simulation_toolbar.py
"""
Run Simulation -- toolbar de definicion de escenario (GIS command bar).

Fase 4 (GIS Workstation): adds "Escenario compuesto" -- permite definir
un shock en VARIOS sectores a la vez en el mismo estado (un paquete de
inversion real casi nunca golpea un solo sector). Por defecto queda
apagado y el comportamiento es EXACTAMENTE el mismo de antes (un
sector, un monto) -- el modo compuesto es un colapso hacia el mismo
caso cuando solo se elige 1 sector (ver
tests/test_simular_multiple.py::test_single_sector_matches_simular_exactly).

No ejecuta la simulacion -- eso sigue siendo responsabilidad exclusiva
de la pagina (EJECUCION), que decide cuando llamar a
`modelo.simular_multiple()` / `run_simulation_engine()`.
"""
from __future__ import annotations

import streamlit as st

from app.helpers.formatting import md
from app.helpers.simulation_formatting import format_money


def render_toolbar(modelo) -> dict:
    """Renderiza la barra de definicion de escenario y devuelve la
    configuracion elegida por el usuario, incluyendo `shocks`
    (`{sector_idx: monto_pesos}`, 1 o mas entradas segun el modo)."""
    st.markdown('<div class="toolbar-wrap">', unsafe_allow_html=True)
    t1, t2, t3, t4, t5 = st.columns([1.3, 1.7, 1.1, 1.1, 0.9])

    with t1:
        nombres_estados = sorted(modelo.mapa_estados.keys())
        estado_nombre = st.selectbox("Region", nombres_estados, index=0)
        estado_key = modelo.mapa_estados[estado_nombre]

    df_sec = modelo.df_sectores
    opciones_sector = [f"{r.scian} — {r.nombre}" for _, r in df_sec.iterrows()]

    compuesto = st.checkbox(
        "➕ Escenario compuesto — varios sectores a la vez",
        value=False, key="toolbar_compuesto",
        help="Reparte el shock entre varios sectores del mismo estado "
             "(p.ej. un paquete de inversión). El modelo es lineal: el "
             "resultado es matemáticamente idéntico a sumar cada sector "
             "por separado.",
    )

    if not compuesto:
        with t2:
            sel_sector = st.selectbox("Economic Sector", opciones_sector, index=0)
            scian_sel = sel_sector.split(" — ")[0]
            sector_row = df_sec[df_sec["scian"].astype(str) == str(scian_sel)].iloc[0]
            sector_idx = int(sector_row["indice"])
            sector_name = sector_row["nombre"]

        with t3:
            monto_pesos = st.number_input(
                "Shock (MXN)", value=100_000_000.0,
                min_value=-1e12, max_value=1e12, step=10_000_000.0, format="%.0f",
            )

        shocks = {sector_idx: monto_pesos}

    else:
        seleccionados = st.multiselect(
            "Sectores del escenario", opciones_sector,
            default=[opciones_sector[0]], key="toolbar_sectores_compuesto",
        )
        if not seleccionados:
            st.warning("Selecciona al menos un sector para el escenario compuesto.")
            seleccionados = [opciones_sector[0]]

        shocks = {}
        nombres_incluidos = []
        n_cols = min(len(seleccionados), 4)
        cols_montos = st.columns(n_cols)
        for i, sel in enumerate(seleccionados):
            scian_sel = sel.split(" — ")[0]
            row = df_sec[df_sec["scian"].astype(str) == scian_sel].iloc[0]
            with cols_montos[i % n_cols]:
                monto_i = st.number_input(
                    f"{row['nombre'][:22]} (MXN)", value=100_000_000.0,
                    min_value=-1e12, max_value=1e12, step=10_000_000.0,
                    format="%.0f", key=f"monto_compuesto_{scian_sel}",
                )
            shocks[int(row["indice"])] = monto_i
            nombres_incluidos.append(row["nombre"])

        sector_name = (
            nombres_incluidos[0] if len(nombres_incluidos) == 1
            else f"{nombres_incluidos[0]} +{len(nombres_incluidos) - 1} sector(es)"
        )
        monto_pesos = sum(shocks.values())

    with t4:
        rho = st.slider("ρ — Spatial Decay", 0.0, 0.95, 0.35, 0.01)

    with t5:
        st.markdown('<div style="height:26px;"></div>', unsafe_allow_html=True)
        launch = st.button("▶ Launch", type="primary", use_container_width=True)

    chip_sector = "🏭 <b>Sectores</b>" if compuesto and len(shocks) > 1 else "🏭 <b>Sector</b>"
    md(f"""
    <div class="chip-row">
        <span class="chip accent">📍 <b>Region</b>{estado_nombre}</span>
        <span class="chip accent">{chip_sector}{sector_name}</span>
        <span class="chip accent">💰 <b>Shock total</b>{format_money(monto_pesos)}</span>
        <span class="chip accent">🌊 <b>ρ</b>{rho:.2f}</span>
    </div>
    """)
    st.markdown('</div>', unsafe_allow_html=True)

    return {
        "estado_nombre": estado_nombre,
        "estado_key": estado_key,
        "shocks": shocks,
        "sector_name": sector_name,
        "monto_pesos": monto_pesos,
        "rho": rho,
        "launch": launch,
    }
