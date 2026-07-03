# Lattise Geospatial Engine — SEW (Spatial Economic Warehouse)

Scaffold inicial construido a partir de `SEW_Engine_Scientific_Specification_v3.pdf`
(Nomenclatura: **SEW** (Warehouse) → **SSD** (Shock Dataset) → **SEE** (Econometric Model)).

## Estado actual

| Stage | Módulo | Estado |
|---|---|---|
| 1. Raw Data | `warehouse/ageb_loader.py::load()` | ✅ Implementado |
| 2. Validation | `warehouse/ageb_loader.py::validate()` | ✅ Implementado — 6 checks, sin descarte silencioso |
| 3. Normalization | `warehouse/ageb_loader.py::normalize()` | ✅ Implementado — CRS EPSG:6372, área/perímetro/centroide |
| 3-4. DENUE + Crosswalk | `warehouse/denue_loader.py`, `warehouse/crosswalk.py` | ⏳ Pendiente (siguiente bloque) |
| 5. Warehouse | `warehouse/builder.py` | ⏳ Pendiente |
| 6. QA | `analytics/diagnostics.py` | ⏳ Pendiente |
| 7. Allocation | `allocation/allocator.py`, `allocation/weights.py` | ⏳ Pendiente |
| 8. Simulation (SEE) | `allocation/simulation.py` | ⏳ Pendiente — Phase 3, depende de panel DENUE |
| 9. Visualization | `visualization/maps.py` | ⏳ Pendiente |
| — | `graph/network.py` (Matriz M) | ⏳ Pendiente |

## Por qué se empezó por `AGEBLoader`

Es el único componente cuyo insumo (Marco Geoestadístico INEGI) y método
de trabajo (ingesta → validación explícita → normalización a EPSG:6372)
ya existen en `lattise_spatial`. El resto del pipeline (DENUE, crosswalk,
warehouse builder) depende de que esta pieza esté cerrada primero, porque
es la que define la geometría base (`g ∈ G`) sobre la que se hace el
Spatial Join de Stage 4.

## Integración con `lattise_spatial`

`ageb_loader.py` intenta importar `lattise_spatial` para reutilizar su
ingesta multi-formato y su normalización de CRS. Si los nombres de
función reales de tu paquete difieren de los asumidos
(`lattise_spatial.io.read_vector`, `lattise_spatial.crs.normalize_crs`,
`lattise_spatial.export.to_geoparquet`), el loader cae automáticamente a
un modo nativo con `geopandas` puro — es decir, **funciona hoy sin
lattise_spatial instalado**, y basta con ajustar el bloque
`_import_lattise_spatial()` cuando confirmes la firma exacta.

## Principio de diseño clave: sin descarte silencioso

`AGEBLoader.validate()` **nunca elimina filas**. Etiqueta cada geometría
con 6 columnas booleanas (`chk_geom_not_null`, `chk_geom_not_empty`,
`chk_geom_is_valid`, `chk_geom_type_ok`, `chk_area_positive`,
`chk_id_unique`) más una columna resumen `_valid_geometry`, y genera un
`AGEBValidationReport` auditable. El descarte real ocurre únicamente si
llamas explícitamente a `filter_valid()` — paso deliberado y separado,
igual que en `lattise_spatial`.

## Cómo correrlo

```bash
pip install -r requirements.txt
python -m pytest tests/ -v

# Sobre un shapefile/gpkg/geojson real de AGEBs:
python -m spatial.warehouse.ageb_loader ruta/a/ageb_estatal.shp
```

## Siguiente bloque de trabajo sugerido

1. `DENUELoader` (Stage 2-3 sobre el DENUE: limpieza de coordenadas, mismo
   patrón validate/normalize).
2. `CrosswalkBuilder` (mapeo SCIAN → 78 sectores SERIO, reutilizando
   `ModeloEconomico.sectores` / `sector_names` de `loader.py`).
3. `warehouse/builder.py` (Stage 5: Spatial Join vía STRtree, cálculo de ω,
   serialización de `warehouse.parquet` + `metadata.json`).
