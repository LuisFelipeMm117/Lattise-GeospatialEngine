"""Regression checks for the Plotly 7 Mapbox-to-MapLibre migration."""
from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_ATTRIBUTES = {
    "choropleth_mapbox",
    "scatter_mapbox",
    "line_mapbox",
    "density_mapbox",
    "Choroplethmapbox",
    "Scattermapbox",
    "Densitymapbox",
}
_LEGACY_KEYWORDS = {"mapbox_style", "mapbox_zoom", "mapbox_center"}


def test_app_does_not_use_removed_plotly_mapbox_apis():
    """Plotly 7 removed these APIs; a simulation must not fail at render time."""
    offenders = []
    for path in (_REPO_ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _LEGACY_ATTRIBUTES:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno} ({node.attr})")
            if isinstance(node, ast.keyword) and node.arg in _LEGACY_KEYWORDS:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno} ({node.arg})")

    assert not offenders, "Removed Plotly Mapbox API usage: " + ", ".join(offenders)
