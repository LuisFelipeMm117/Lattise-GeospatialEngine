# Decision Support Engine — `spatial/decision_support/`

## Qué es

Un módulo nuevo del backend (`spatial/decision_support/`) que organiza
todo lo que el motor **ya sabe** de cada AGEB, municipio y comunidad
económica en **perfiles territoriales reutilizables**.

| Módulo existente        | Pregunta que responde |
|---|---|
| Simulation Engine (Stage 8C) | ¿Qué ocurre? |
| Cluster Intelligence         | ¿Por qué ocurre? |
| **Decision Support Engine**  | **¿Qué sabemos de este territorio, usando toda la información existente?** |

Este módulo **nunca** responde "¿dónde invertir?" ni "¿cuál es la mejor
ubicación?" — esas preguntas son responsabilidad exclusiva del
frontend (p.ej. Opportunity Explorer).

## Qué NO hace

- No recalcula simulaciones, no reconstruye `warehouse.parquet`,
  `graph.gal` ni `sector_cluster.json`.
- No agrega IA, Machine Learning, optimización ni modelos
  econométricos nuevos.
- No genera scores ni recomendaciones — cada insight es una oración
  descriptiva construida a partir de un valor que ya existía en algún
  artefacto congelado.
- No modifica ningún archivo de `spatial/`, `serio/`, `tests/`,
  `examples/` ni `app/` — es un paquete enteramente nuevo.

## Entradas (todas artefactos ya existentes)

| Artefacto | Origen | Obligatorio |
|---|---|---|
| `warehouse.parquet` | Stage 5 (Warehouse Builder), CERRADO | Sí |
| `sector_cluster.json` | `scripts/build_sector_clusters.py`, congelado offline | Sí |
| Catálogo de sectores SERIO (código → nombre) | `serio/loader.py::ModeloEconomico.sector_names` | Sí (puede ser `{}`) |
| `graph.gal` / `SpatialMatrix` | Stage 8A (Spatial Graph Builder), CERRADO | Opcional |
| `simulation_gdf` / `SimulationReport` | Stage 8C (Simulation Engine), CERRADO | Opcional |

Ninguno de estos artefactos se recalcula: el módulo únicamente los lee
(`spatial.decision_support.loader`) o los recibe ya cargados en
memoria (p.ej. `st.session_state["simulation_gdf"]` en la capa de
aplicación).

## Salida — `DecisionSupportReport`

Objeto serializable (mismo patrón `to_dict()`/`to_json()`/`summary()`
que `AllocationReport`/`SimulationReport`) con:

- `ageb_profiles`: `dict[cvegeo, AGEBProfile]` — un perfil por AGEB
  (municipio, comunidad económica, sector dominante, participación,
  impacto directo/indirecto/propagado si hay simulación, ranking,
  vecinos, municipios conectados, comunidades relacionadas).
- `municipality_profiles`: `dict[municipio, MunicipalityProfile]`.
- `community_profiles`: `dict[cluster_id, CommunityProfile]` — incluye
  comunidades sin AGEBs locales, con `n_agebs=0` explícito.
- `relationships`: la cadena explícita
  `AGEB → Municipio → Comunidad → AGEBs relacionadas → Sectores`
  (`spatial.decision_support.relationships.TerritorialRelationships`).
- `insights`: oraciones descriptivas por AGEB/municipio/comunidad/
  portafolio completo (`spatial.decision_support.insights`).
- `aggregation_report` / `warnings`: trazabilidad — AGEBs sin perfil,
  sectores sin comunidad Louvain asignada, nunca descartados en
  silencio.

Exportable a JSON (`report.to_json(path)`), a `pandas.DataFrame`
(`report.to_dataframe()`) y a Parquet (`report.to_parquet(path)`).

## Uso

```python
from spatial.decision_support import (
    build_decision_support_report,
    load_cluster_artifact,
    load_sector_names,
    load_spatial_matrix,
    load_warehouse_gdf,
)

report = build_decision_support_report(
    warehouse_gdf=load_warehouse_gdf(),
    cluster_artifact=load_cluster_artifact(),
    sector_names=load_sector_names(),
    spatial_matrix=load_spatial_matrix(gal_path, metadata_path),   # opcional
    simulation_gdf=st.session_state.get("simulation_gdf"),          # opcional
)

report.summary()                    # texto legible
report.ageb("2201400010001")        # dict — perfil de un AGEB puntual
report.community("0")               # dict — perfil de una comunidad
report.to_json("data/decision_support/report.json")
```

## Estructura de archivos

```
spatial/decision_support/
├── __init__.py        # API pública del paquete
├── constants.py        # nombres de columna / rutas por defecto (reimporta, no redefine)
├── territory.py         # parsing puro de cvegeo → municipio/entidad
├── formatting.py         # formato numérico puro para insights
├── loader.py               # lectura de los 4 artefactos ya congelados
├── aggregation.py           # groupby/argmax puros sobre warehouse + cluster_artifact
├── profiles.py                # AGEBProfile / MunicipalityProfile / CommunityProfile
├── relationships.py            # cadena AGEB→Municipio→Comunidad→AGEBs→Sectores
├── insights.py                  # oraciones descriptivas, deterministas
└── report.py                     # orquestación + DecisionSupportReport

tests/test_decision_support.py   # suite completa (18 pruebas, fixtures genuinas)
```

## Pruebas

```
pytest tests/test_decision_support.py -v
```

18 pruebas, sin mocks: `warehouse.parquet` y `graph.gal` se construyen
con `WarehouseBuilder`/`SpatialGraphBuilder` reales sobre una grilla
AGEB sintética de 3×2 celdas repartida en dos municipios INEGI reales
("014"/"015"); `simulation_gdf` se produce con `run_simulation_engine()`
real. Cubren explícitamente: AGEBs sin geometría, comunidades vacías,
municipios vacíos, warehouse completamente vacío, catálogo de sectores
ausente, serialización (JSON/Parquet/DataFrame) y consistencia
aritmética entre agregados AGEB → municipio → comunidad.

Suite completa del repositorio tras la incorporación: **306/306
pruebas pasan** (288 preexistentes + 18 nuevas), sin ninguna
modificación a `spatial/`, `serio/`, `tests/` ni `examples/` — ver
`git status` (solo dos rutas nuevas: `spatial/decision_support/` y
`tests/test_decision_support.py`).

## Nota para Opportunity Explorer (Módulo 5)

Este módulo deja lista la base para que, en un futuro incremento,
`app/pages/5_Opportunity_Explorer.py` deje de calcular agregaciones e
insights por su cuenta (`app/helpers/aggregation.py`,
`app/helpers/insights.py`) y en su lugar consuma directamente un
`DecisionSupportReport` ya construido. **Ese refactor no forma parte
de este entregable** — ningún archivo de `app/` fue modificado; los
helpers existentes (`app/helpers/*`, `app/panels/*`) siguen
funcionando exactamente igual que antes.
