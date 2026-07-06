# spatial/simulation/__init__.py
"""
Simulation — Spatial Econometric Engine (SEE, Especificación Formal v3.0,
Sección 8, Stage 8).

Paquete independiente de `spatial.allocation` y `spatial.graph`: consume
únicamente los artefactos ya persistidos por ambos (`shock_ageb.parquet` y
`graph.gal`/`graph_metadata.json`) más los parámetros propios del modelo
espacial (p.ej. ρ). No recalcula ni modifica nada de Stage 1→7 ni del
Spatial Graph Builder.

Incremento 1 (este): reconstrucción y validación de la matriz espacial `W`
a partir de `graph.gal` — `spatial.simulation.matrix.SpatialMatrix`.
"""
from spatial.simulation.matrix import SpatialMatrix, SpatialMatrixReport, load_gal

__all__ = ["SpatialMatrix", "SpatialMatrixReport", "load_gal"]