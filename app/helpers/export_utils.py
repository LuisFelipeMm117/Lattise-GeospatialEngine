# app/helpers/export_utils.py
"""
Opportunity Explorer — Export (según el Sprint: "utilizando la
infraestructura existente").

PNG y GeoJSON se generan reutilizando literalmente
`spatial.visualization.maps` (Stage 9, CERRADO) — `render_choropleth()`
y `export_geojson()` — sin reimplementar renderizado ni reproyección.
Ambas funciones de Stage 9 escriben a disco, por lo que aquí solo se
las envuelve para producir bytes descargables vía `st.download_button`,
usando un directorio temporal (nunca se escribe sobre
`data/visualization/`, que es el artefacto oficial de Stage 9).

CSV y JSON no requieren infraestructura especial — son una
serialización directa de tablas de presentación ya construidas por
`app.helpers.aggregation`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spatial.visualization.maps import export_geojson, render_choropleth  # noqa: E402


def geojson_bytes(gdf: gpd.GeoDataFrame, value_col: str | None = None, id_col: str = "cvegeo") -> bytes:
    """Envuelve `spatial.visualization.maps.export_geojson` (Stage 9,
    CERRADO) para devolver bytes descargables en vez de escribir en
    `data/visualization/`."""
    columns = [c for c in gdf.columns if c not in ("geometry", id_col)] if value_col is None else [value_col]
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "export.geojson"
        export_geojson(gdf, out_path, id_col=id_col, columns=columns)
        return out_path.read_bytes()


def choropleth_png_bytes(
    gdf: gpd.GeoDataFrame, value_col: str, id_col: str = "cvegeo",
    title: str | None = None, legend_label: str | None = None,
) -> bytes:
    """Envuelve `spatial.visualization.maps.render_choropleth` (Stage 9,
    CERRADO) para devolver bytes PNG descargables."""
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "export.png"
        render_choropleth(
            gdf, value_col, out_path, id_col=id_col,
            title=title, legend_label=legend_label,
        )
        return out_path.read_bytes()


def csv_bytes(df: pd.DataFrame, drop_cols: tuple[str, ...] = ("geometry",)) -> bytes:
    cols_to_drop = [c for c in drop_cols if c in df.columns]
    return pd.DataFrame(df).drop(columns=cols_to_drop).to_csv(index=False).encode("utf-8")


def json_bytes(payload) -> bytes:
    if isinstance(payload, pd.DataFrame):
        cols_to_drop = [c for c in ("geometry",) if c in payload.columns]
        payload = pd.DataFrame(payload).drop(columns=cols_to_drop).to_dict(orient="records")
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
