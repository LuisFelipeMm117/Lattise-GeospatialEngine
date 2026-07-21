# app/components/simulation_toolbar.py
"""
Run Simulation -- toolbar de definicion de escenario (GIS command bar).

Extraido de app/pages/1_Run_Simulation.py sin cambios de comportamiento
-- el bloque de widgets es identico, solo se envolvio en una funcion
que devuelve la configuracion elegida (antes viva como variables sueltas
a nivel de modulo).
"""
from __future__ import annotations

import streamlit as st

from app.helpers.formatting import md
from app.helpers.simulation_formatting import format_money


def render_toolbar(modelo) -> dict:
    """Renderiza la barra de definicion de escenario y devuelve la
    configuracion elegida por el usuario. No ejecuta la simulacion --
    eso sigue siendo responsabilidad exclusiva de la pagina (EJECUCIÓN),
    que decide cuando llamar a `modelo.simular()` /
    `run_simulation_engine()`."""
    st.markdown('<div class="toolbar-wrap">', unsafe_allow_html=True)
    t1, t2, t3, t4, t5 = st.columns([1.3, 1.7, 1.1, 1.1, 0.9])
    
    with t1:
        nombres_estados = sorted(modelo.mapa_estados.keys())
        estado_nombre = st.selectbox("Region", nombres_estados, index=0)
        estado_key = modelo.mapa_estados[estado_nombre]
    
    with t2:
        df_sec = modelo.df_sectores
        opciones_sector = [f"{r.scian} — {r.nombre}" for _, r in df_sec.iterrows()]
        sel_sector = st.selectbox("Economic Sector", opciones_sector, index=0)
        scian_sel = sel_sector.split(" — ")[0]
        sector_row = df_sec[df_sec["scian"].astype(str) == str(scian_sel)].iloc[0]
        sector_idx = int(sector_row["indice"])
        sector_name = sector_row["nombre"]
    
    with t3:
        monto_pesos = st.number_input(
            "Shock (MXN)",
            value=100_000_000.0,
            min_value=-1e12,
            max_value=1e12,
            step=10_000_000.0,
            format="%.0f",
        )
    
    with t4:
        rho = st.slider("ρ — Spatial Decay", 0.0, 0.95, 0.35, 0.01)
    
    with t5:
        st.markdown('<div style="height:26px;"></div>', unsafe_allow_html=True)
        launch = st.button("▶ Launch", type="primary", use_container_width=True)
    
    md(f"""
    <div class="chip-row">
        <span class="chip accent">📍 <b>Region</b>{estado_nombre}</span>
        <span class="chip accent">🏭 <b>Sector</b>{sector_name}</span>
        <span class="chip accent">💰 <b>Shock</b>{format_money(monto_pesos)}</span>
        <span class="chip accent">🌊 <b>ρ</b>{rho:.2f}</span>
    </div>
    """)
    st.markdown('</div>', unsafe_allow_html=True)

    return {
        "estado_nombre": estado_nombre,
        "estado_key": estado_key,
        "sector_idx": sector_idx,
        "sector_name": sector_name,
        "monto_pesos": monto_pesos,
        "rho": rho,
        "launch": launch,
    }
