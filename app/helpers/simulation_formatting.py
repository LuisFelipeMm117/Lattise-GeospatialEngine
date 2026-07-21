# app/helpers/simulation_formatting.py
"""
Run Simulation -- formato de moneda y magnitudes.

Extraido de app/pages/1_Run_Simulation.py sin cambios de comportamiento.
Se mantiene SEPARADO de app/helpers/formatting.py a proposito:
`format_compact` de esta pagina usa 2 decimales y agrega un nivel "B"
(miles de millones) que la version compartida (usada por Opportunity
Explorer y Cluster Intelligence) no tiene -- unificar los dos habria
cambiado la precision mostrada en alguna de las paginas sin que nadie
lo pidiera explicitamente. `municipio_code` y `md`, que SI eran
identicos a los de app/helpers/formatting.py, se dejaron de duplicar
(ver import en la pagina).
"""
from __future__ import annotations

def format_money(value: float) -> str:
    """Formatea un monto a $X.XX K/M/B MXN. Presentación pura, no transforma
    el valor subyacente producido por el motor."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000_000:
        return f"{sign}${v / 1_000_000_000:,.2f} B MXN"
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:,.2f} M MXN"
    if v >= 1_000:
        return f"{sign}${v / 1_000:,.2f} K MXN"
    return f"{sign}${v:,.2f} MXN"


def format_compact(value: float) -> str:
    """Formato compacto para KPIs/rankings (sin símbolo de moneda)."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000_000:
        return f"{sign}{v / 1_000_000_000:,.2f}B"
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:,.2f}M"
    if v >= 1_000:
        return f"{sign}{v / 1_000:,.2f}K"
    return f"{sign}{v:,.2f}"
