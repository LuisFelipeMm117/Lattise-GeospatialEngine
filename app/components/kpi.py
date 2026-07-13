# app/components/kpi.py
"""
Opportunity Explorer — componentes visuales reutilizables: grid de KPIs,
leyendas de mapa (gradiente y categórica). Presentación pura — reciben
valores ya calculados, nunca calculan nada.
"""
from __future__ import annotations

from app.helpers.formatting import format_compact, md


def render_kpi_grid(items: list[tuple[str, str]]) -> None:
    """`items`: lista de (label, value) ya formateados. Se dibuja en un
    grid de 2 columnas dentro de `.detail-kpi-row`."""
    rows_html = "".join(
        f'<div class="detail-kpi"><div class="detail-kpi-label">{label}</div>'
        f'<div class="detail-kpi-value">{value}</div></div>'
        for label, value in items
    )
    md(f'<div class="detail-kpi-row">{rows_html}</div>')


def render_tag_row(tags: list[str], max_tags: int = 12) -> None:
    tags_html = "".join(f'<span class="tag">{t}</span>' for t in tags[:max_tags])
    md(f'<div class="tag-row">{tags_html}</div>')


def grad_legend(title: str, vmin: float, vmax: float, css_gradient: str) -> str:
    return f"""
    <div class="legend-card">
      <div class="legend-title">{title}</div>
      <div class="legend-grad" style="background:{css_gradient};"></div>
      <div class="legend-scale-row"><span>{format_compact(vmin)}</span><span>{format_compact(vmax)}</span></div>
    </div>
    """


def categorical_legend(title: str, items: list[tuple[str, str]]) -> str:
    chips = "".join(
        f'<div class="legend-chip"><span class="dot" style="background:{color};"></span>{label}</div>'
        for label, color in items
    )
    return f"""
    <div class="legend-card">
      <div class="legend-title">{title}</div>
      <div class="legend-chip-row">{chips}</div>
    </div>
    """
