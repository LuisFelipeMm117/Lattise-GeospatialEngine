# Lattise Geospatial Engine

Motor espacial-económico de **Lattise**: distribuye la actividad económica
nacional (modelo SERIO, 78 sectores, Insumo-Producto regionalizado
FLQ+RAS) al nivel de AGEB (INEGI, Marco Geoestadístico), propaga shocks
de demanda con un operador espacial `Y = (I - ρW)⁻¹·S`, y expone todo lo
anterior a través de una consola operativa en Streamlit ("Lattise Studio").

Nomenclatura del pipeline: **SEW** (Spatial Economic Warehouse) →
**SSD** (Spatial Shock Distributor) → **SEE** (Spatial Econometric
Engine). Ver `SEW_Engine_Scientific_Specification_v3.pdf` para el
diseño científico completo.

## Estado actual

| Stage | Módulo | Estado |
|---|---|---|
| 1–2. Ingesta + Validación AGEB | `warehouse/ageb_loader.py` | ✅ Cerrado |
| 3. Normalización (CRS, geometría) | `warehouse/ageb_loader.py::normalize()` | ✅ Cerrado |
| 3–4. DENUE + Crosswalk SCIAN→SERIO | `warehouse/denue_loader.py`, `warehouse/crosswalk.py`, `warehouse/crosswalk_maestro.py` | ✅ Cerrado — autoría jerárquica |
| 5. Warehouse (Spatial Join, ω) | `warehouse/builder.py` | ✅ Cerrado |
| 6. QA / Diagnostics | `analytics/diagnostics.py` | ✅ Cerrado |
| 7. Shock Allocation (SSD) | `allocation/allocator.py`, `allocation/weights.py` | ✅ Cerrado |
| 8A. Spatial Graph (Matriz M) | `graph/network.py` | ✅ Cerrado |
| 8B–8D. Simulación (SEE) | `simulation/matrix.py`, `simulation/operator.py`, `simulation/engine.py`, `simulation/scenario.py` | ✅ Cerrado |
| 9. Visualización | `visualization/maps.py` | ✅ Cerrado |
| — | Decision Support Engine | ✅ Cerrado — ver `spatial/decision_support/README.md` |
| 10. API REST | — | ⏳ No presente en este repositorio — confirmar paradero antes de planear la migración de infraestructura |

Todos los stages marcados ✅ tienen tests dedicados con fixtures
genuinas (nunca mockeadas) en `tests/`. Correr `pytest tests/ -v` para
el detalle.

## Arquitectura

```
spatial/            Motor — CERRADO. Nunca se modifica desde fuera;
  warehouse/         solo se consume vía sus APIs públicas.
  graph/
  simulation/
  visualization/
  analytics/
  allocation/
  decision_support/  Capa de perfiles territoriales (AGEB/municipio/
                      comunidad) que consume el motor de solo lectura.
serio/               Modelo Insumo-Producto nacional (78 sectores).
app/                 Lattise Studio — Streamlit. Presentación pura:
  helpers/            ningún archivo aquí recalcula pesos, comunidades
  components/         ni impactos — todo eso vive en spatial/.
  panels/
  pages/
tests/               Suite de pytest — un archivo por módulo del motor.
scripts/             Utilidades offline (crosswalk maestro, clusters
                      Louvain) que producen artefactos congelados.
examples/            Scripts de referencia end-to-end.
```

**Invariante arquitectónico:** `spatial/`, `serio/`, `tests/` y
`examples/` son módulos cerrados — código nuevo los consume vía sus
APIs públicas (`to_dict()/to_json()/summary()`), nunca los reescribe.
`app/` es la única capa que puede cambiar libremente, y su única fuente
de verdad para peso/comunidad/sector dominante es
`spatial/decision_support/` (ver ese README para el contrato completo).

## Principios de diseño

- **Sin descarte silencioso.** `validate()` etiqueta con columnas
  booleanas; el descarte real (`filter_valid()`) es un paso explícito
  y separado en cada loader.
- **Islas explícitas.** AGEBs sin vecinos se reportan, nunca se les
  asigna un fallback artificial. Sectores sin cobertura espacial se
  reportan, nunca se excluyen en silencio.
- **Una sola fuente de verdad por magnitud.** Si dos partes del código
  calculan el mismo peso/dominancia/impacto, es un bug de arquitectura,
  no una optimización — ver el historial de refactors en
  `app/helpers/decision_support_bridge.py`.

## Cómo correrlo

```bash
pip install -r requirements.txt

# Suite completa del motor
python -m pytest tests/ -v

# Lattise Studio (Streamlit)
streamlit run app/home.py
```

## Siguiente bloque de trabajo sugerido

1. Confirmar si el Stage 10 (API REST Flask) existe en otra rama/repo
   — bloqueante para la migración a Railway + Next.js.
2. Cerrar la duplicación de agregación restante en
   `app/pages/4_Spatial_Cluster_Intelligence.py` (mismo patrón ya
   aplicado a Opportunity Explorer).
3. Descomponer `app/pages/1_Run Simulation.py` (monolito de ~1,450
   líneas) en `helpers/components/panels`, siguiendo el patrón de
   Opportunity Explorer, antes de definir las Fases 4–5 del GIS
   Workstation.
