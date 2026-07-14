# spatial/decision_support/report.py
"""
Decision Support Engine — Orquestación y `DecisionSupportReport`
(Especificación Formal v3.0 — nuevo incremento, posterior a Stage 9).

Responsabilidad:
    El motor actualmente responde "¿qué ocurre?" (Simulation Engine,
    Stage 8C) y "¿por qué ocurre?" (Cluster Intelligence, análisis
    estructural del MIP). Este módulo responde una tercera pregunta:
    "¿qué sabemos de este territorio, usando toda la información ya
    calculada?" — organiza, sin recalcular nada, los artefactos ya
    congelados en perfiles territoriales reutilizables.

    Este módulo NUNCA responde:
        - "¿Dónde invertir?"
        - "¿Cuál es la mejor ubicación?"
    Esas preguntas son responsabilidad exclusiva de la capa de
    aplicación (`app/`, p.ej. Opportunity Explorer) — este módulo solo
    describe, nunca prioriza ni recomienda.

Este módulo:
    - NO reconstruye `warehouse.parquet`, `graph.gal`,
      `sector_cluster.json` ni `simulation_gdf` — es un consumidor puro
      de esos cuatro artefactos, exactamente igual que
      `spatial.simulation.engine` es consumidor puro de
      `shock_ageb.parquet` y `graph.gal` (mismo criterio de Layer
      Isolation y Explicit Data Contracts, Sección 5).
    - NO recalcula ninguna simulación económica ni espacial — si se le
      pasa `simulation_gdf`, únicamente LEE sus columnas de impacto
      (`shock_directo`, `impacto_indirecto`, `impacto_propagado`,
      `es_isla`) ya producidas por `run_simulation_engine()`
      (Stage 8C, CERRADO).
    - NO agrega IA, Machine Learning, optimización ni modelos
      econométricos nuevos — todos los agregados son groupby/argmax/
      merge deterministas sobre columnas ya existentes
      (`spatial.decision_support.aggregation`).
    - NO descarta AGEBs, municipios o comunidades en silencio: cada
      subconjunto vacío (comunidad sin AGEBs locales, municipio sin
      AGEBs asignados, AGEB sin geometría) queda representado
      explícitamente en el reporte con sus campos en 0/None/[] — nunca
      se omite la entrada.

Entradas (Sección "ENTRADAS" del encargo — todos artefactos YA
existentes, consumidos vía `spatial.decision_support.loader` o
inyectados directamente por el caller cuando ya viven en memoria,
p.ej. `st.session_state` en la capa de aplicación):
    - `warehouse.parquet`               (obligatorio)
    - `sector_cluster.json`             (obligatorio)
    - catálogo de sectores SERIO        (obligatorio, puede ser `{}`)
    - `graph.gal` / `SpatialMatrix`     (opcional)
    - `simulation_gdf` / `simulation_report` (opcional)

Salida:
    `DecisionSupportReport` — serializable a JSON, Parquet (perfiles de
    AGEB) y `pandas.DataFrame`, mismo patrón `to_dict()`/`to_json()`/
    `summary()` que `AllocationReport`/`SimulationReport`/
    `SpatialMatrixReport`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import geopandas as gpd
import pandas as pd

from spatial.decision_support.aggregation import build_ageb_universe
from spatial.decision_support.constants import (
    CLUSTER_ID_COL,
    ES_ISLA_COL,
    ID_COL,
    IMPACTO_DIRECTO_COL,
    IMPACTO_INDIRECTO_COL,
    IMPACTO_PROPAGADO_COL,
    MUNICIPIO_COL,
    SECTOR_SERIO_COL,
)
from spatial.decision_support.insights import (
    ageb_insights,
    community_insights,
    municipality_insights,
    portfolio_insights,
)
from spatial.decision_support.profiles import AGEBProfile, CommunityProfile, MunicipalityProfile
from spatial.decision_support.relationships import TerritorialRelationships, build_territorial_relationships

logger = logging.getLogger("sew.decision_support.report")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

DEFAULT_TOP_N = 5


@dataclass
class DecisionSupportReport:
    """Reporte de extremo a extremo del Decision Support Engine —
    mismo patrón `to_dict()`/`to_json()`/`summary()` que el resto del
    motor. Ningún campo es un score ni una recomendación."""

    generated_at: str
    n_agebs: int
    n_municipios: int
    n_comunidades: int
    has_simulation: bool
    has_spatial_matrix: bool

    ageb_profiles: dict = field(default_factory=dict)          # cvegeo -> AGEBProfile.to_dict()
    municipality_profiles: dict = field(default_factory=dict)  # municipio -> MunicipalityProfile.to_dict()
    community_profiles: dict = field(default_factory=dict)     # str(cluster_id) -> CommunityProfile.to_dict()

    relationships: dict = field(default_factory=dict)

    insights: dict = field(default_factory=dict)
    """`{"portfolio": [...], "comunidades": {cluster_id: [...]},
    "municipios": {municipio: [...]}, "agebs": {cvegeo: [...]}}` —
    únicamente insights descriptivos, ver `spatial.decision_support.insights`."""

    aggregation_report: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    # ── Serialización — mismo patrón que el resto del motor ────────────
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def to_dataframe(self) -> pd.DataFrame:
        """`AGEBProfile`s como `pandas.DataFrame` — una fila por AGEB.
        No incluye geometría (usa `warehouse.parquet`/`ageb_gdf` para
        eso); es una vista tabular de presentación, no un artefacto
        geoespacial nuevo."""
        if not self.ageb_profiles:
            return pd.DataFrame()
        return pd.DataFrame(list(self.ageb_profiles.values()))

    def to_parquet(self, path: str | Path) -> Path:
        """Serializa los perfiles de AGEB (sin geometría) a Parquet —
        útil para inspección tabular fuera de Python. Para el
        `GeoDataFrame` con geometría, usa `ageb_gdf` directamente en el
        caller (este reporte es intencionalmente agnóstico de
        geopandas en su forma serializada, igual que
        `AllocationReport`/`SimulationReport` no serializan geometría
        en su `to_json()`)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = self.to_dataframe()
        # Columnas de tipo lista no son nativas de Parquet/Arrow como
        # escalares — se serializan a JSON string, nunca se descartan.
        for col in df.columns:
            if df[col].apply(lambda v: isinstance(v, (list, dict))).any():
                df[col] = df[col].apply(lambda v: json.dumps(v, ensure_ascii=False))
        df.to_parquet(path)
        return path

    def summary(self) -> str:
        lines = [
            f"Decision Support Report — {self.n_agebs} AGEB(s), {self.n_municipios} municipio(s), "
            f"{self.n_comunidades} comunidad(es) económica(s)",
            f"  simulación cargada: {'sí' if self.has_simulation else 'no'}  ·  "
            f"matriz espacial cargada: {'sí' if self.has_spatial_matrix else 'no'}",
        ]
        if self.warnings:
            lines.append(f"  ⚠ advertencias: {self.warnings}")
        return "\n".join(lines)

    # ── Accesores de conveniencia (lectura directa, sin lógica nueva) ──
    def ageb(self, cvegeo: str) -> Optional[dict]:
        return self.ageb_profiles.get(str(cvegeo))

    def municipality(self, municipio: str) -> Optional[dict]:
        return self.municipality_profiles.get(str(municipio))

    def community(self, cluster_id) -> Optional[dict]:
        return self.community_profiles.get(str(cluster_id))


# ══════════════════════════════════════════════════════════════════════════
# Orquestación — construcción de perfiles a partir de artefactos ya cargados
# ══════════════════════════════════════════════════════════════════════════
def _build_ageb_profiles(
    ageb_gdf: gpd.GeoDataFrame,
    long_sector: pd.DataFrame,
    relationships: TerritorialRelationships,
    cluster_artifact: dict,
    simulation_gdf: Optional[gpd.GeoDataFrame],
    spatial_matrix,
    id_col: str,
    sector_col: str,
) -> dict[str, AGEBProfile]:
    n_total = len(ageb_gdf)
    clusters_meta = cluster_artifact.get("clusters", {})

    sim_by_ageb: dict = {}
    if simulation_gdf is not None:
        sim_cols = [c for c in (IMPACTO_DIRECTO_COL, IMPACTO_INDIRECTO_COL, IMPACTO_PROPAGADO_COL, ES_ISLA_COL) if c in simulation_gdf.columns]
        sim_df = pd.DataFrame(simulation_gdf.drop(columns="geometry", errors="ignore"))[[id_col, *sim_cols]]
        sim_by_ageb = sim_df.set_index(id_col).to_dict(orient="index")

    profiles: dict[str, AGEBProfile] = {}
    for _, row in ageb_gdf.iterrows():
        ageb = str(row[id_col])
        cluster_id = row.get(CLUSTER_ID_COL)
        cluster_id_int = int(cluster_id) if pd.notna(cluster_id) else None
        cluster_meta = clusters_meta.get(str(cluster_id_int)) if cluster_id_int is not None else None

        sim_row = sim_by_ageb.get(ageb, {})
        impacto_directo = sim_row.get(IMPACTO_DIRECTO_COL)
        impacto_indirecto = sim_row.get(IMPACTO_INDIRECTO_COL)
        impacto_propagado = sim_row.get(IMPACTO_PROPAGADO_COL)
        es_isla = sim_row.get(ES_ISLA_COL)
        if es_isla is None and spatial_matrix is not None:
            try:
                es_isla = bool(spatial_matrix.is_island(ageb))
            except KeyError:
                es_isla = None

        vecinos = relationships.ageb_to_vecinos.get(ageb, [])
        municipios_conectados = sorted({
            relationships.ageb_to_municipio.get(v) for v in vecinos if v in relationships.ageb_to_municipio
        })
        comunidades_relacionadas = sorted({
            relationships.ageb_to_comunidad.get(v)
            for v in vecinos
            if relationships.ageb_to_comunidad.get(v) is not None
        })

        profiles[ageb] = AGEBProfile(
            ageb=ageb,
            municipio=str(row.get(MUNICIPIO_COL, "—")),
            cluster_id=cluster_id_int,
            cluster_nombre=cluster_meta["nombre"] if cluster_meta else None,
            cluster_peso=float(row["cluster_peso"]) if pd.notna(row.get("cluster_peso")) else None,
            peso_metodo=row.get("peso_metodo"),
            sector_dominante=row.get("sector_dominante"),
            sector_dominante_nombre=row.get("sector_dominante_nombre"),
            sector_dominante_peso=float(row["sector_peso"]) if pd.notna(row.get("sector_peso")) else None,
            n_sectores=int(row.get("n_sectores_ageb", 0)) if pd.notna(row.get("n_sectores_ageb")) else 0,
            sectores_presentes=relationships.ageb_to_sectores.get(ageb, []),
            peso_total=float(row.get("peso_total_ageb", 0.0)) if pd.notna(row.get("peso_total_ageb")) else 0.0,
            participacion_pct=float(row.get("participacion_pct", 0.0)),
            ranking=int(row["ranking"]) if pd.notna(row.get("ranking")) else None,
            n_agebs_universo=n_total,
            impacto_directo=float(impacto_directo) if impacto_directo is not None else None,
            impacto_indirecto=float(impacto_indirecto) if impacto_indirecto is not None else None,
            impacto_propagado=float(impacto_propagado) if impacto_propagado is not None else None,
            n_vecinos=len(vecinos),
            agebs_relacionadas=vecinos,
            municipios_conectados=[m for m in municipios_conectados if m is not None],
            comunidades_relacionadas=comunidades_relacionadas,
            es_isla=es_isla,
            cobertura_espacial=(spatial_matrix is not None and ageb in getattr(spatial_matrix, "ids", [])),
        )
    return profiles


def _build_municipality_profiles(
    ageb_profiles: dict[str, AGEBProfile], top_n: int
) -> dict[str, MunicipalityProfile]:
    if not ageb_profiles:
        return {}
    df = pd.DataFrame([p.to_dict() for p in ageb_profiles.values()])
    peso_total_global = df["peso_total"].sum()

    out: dict[str, MunicipalityProfile] = {}
    for municipio, sub in df.groupby("municipio"):
        sub_sorted = sub.sort_values("peso_total", ascending=False)
        has_sim = sub["impacto_propagado"].notna().any()
        out[str(municipio)] = MunicipalityProfile(
            municipio=str(municipio),
            agebs=sorted(sub["ageb"].tolist()),
            n_agebs=int(sub["ageb"].nunique()),
            clusters_presentes=sorted({c for c in sub["cluster_id"].dropna().tolist()}),
            sectores_presentes=sorted({s for lst in sub["sectores_presentes"] for s in lst}),
            peso_total=float(sub["peso_total"].sum()),
            participacion_pct=float(sub["peso_total"].sum() / peso_total_global * 100) if peso_total_global else 0.0,
            impacto_directo_agregado=float(sub["impacto_directo"].sum()) if has_sim else None,
            impacto_indirecto_agregado=float(sub["impacto_indirecto"].sum()) if has_sim else None,
            impacto_propagado_agregado=float(sub["impacto_propagado"].sum()) if has_sim else None,
            impacto_propagado_promedio=float(sub["impacto_propagado"].mean()) if has_sim else None,
            agebs_principales=sub_sorted["ageb"].head(top_n).tolist(),
        )
    return out


def _build_community_profiles(
    ageb_profiles: dict[str, AGEBProfile],
    cluster_artifact: dict,
    sector_names: dict,
    top_n: int,
) -> dict[str, CommunityProfile]:
    clusters_meta = cluster_artifact.get("clusters", {})
    if not clusters_meta:
        return {}

    df = pd.DataFrame([p.to_dict() for p in ageb_profiles.values()]) if ageb_profiles else pd.DataFrame(
        columns=["ageb", "municipio", "cluster_id", "peso_total"]
    )
    peso_total_global = df["peso_total"].sum() if not df.empty else 0.0

    out: dict[str, CommunityProfile] = {}
    for cl_key, cl in clusters_meta.items():
        cluster_id = int(cl["cluster_id"])
        sub = df[df["cluster_id"] == cluster_id] if not df.empty else df
        sub_sorted = sub.sort_values("peso_total", ascending=False) if not sub.empty else sub
        peso_comunidad = float(sub["peso_total"].sum()) if not sub.empty else 0.0

        municipios_principales = (
            sub.groupby("municipio")["peso_total"].sum().sort_values(ascending=False).head(top_n).index.tolist()
            if not sub.empty else []
        )

        out[cl_key] = CommunityProfile(
            cluster_id=cluster_id,
            nombre=cl.get("nombre", f"Comunidad {cluster_id}"),
            n_agebs=int(sub["ageb"].nunique()) if not sub.empty else 0,
            n_municipios=int(sub["municipio"].nunique()) if not sub.empty else 0,
            sectores=cl.get("sectores", []),
            sectores_nombres=[sector_names.get(str(s), f"Sector {s}") for s in cl.get("sectores", [])],
            n_sectores=cl.get("n_sectores", len(cl.get("sectores", []))),
            centralidad_media=cl.get("centralidad_media"),
            bl_media=cl.get("bl_media"),
            fl_media=cl.get("fl_media"),
            peso_total=peso_comunidad,
            participacion_pct=(peso_comunidad / peso_total_global * 100) if peso_total_global else 0.0,
            municipios_principales=municipios_principales,
            agebs_principales=sub_sorted["ageb"].head(top_n).tolist() if not sub.empty else [],
        )
    return out


def build_decision_support_report(
    warehouse_gdf: gpd.GeoDataFrame,
    cluster_artifact: dict,
    sector_names: dict,
    *,
    spatial_matrix=None,
    simulation_gdf: Optional[gpd.GeoDataFrame] = None,
    simulation_report: Optional[Mapping[str, Any]] = None,
    id_col: str = ID_COL,
    sector_col: str = SECTOR_SERIO_COL,
    top_n_principales: int = DEFAULT_TOP_N,
) -> DecisionSupportReport:
    """Pipeline completo del Decision Support Engine:

        warehouse.parquet + sector_cluster.json
            → aggregation.build_ageb_universe()      (perfil AGEB base)
            → relationships.build_territorial_relationships()
            → AGEBProfile / MunicipalityProfile / CommunityProfile
            → insights.*()                            (descriptivos)
            → DecisionSupportReport

    `simulation_gdf` (columnas `shock_directo`/`impacto_indirecto`/
    `impacto_propagado`/`es_isla`, producidas por
    `spatial.simulation.engine.run_simulation_engine()`) y
    `spatial_matrix` (`spatial.simulation.matrix.SpatialMatrix`) son
    OPCIONALES: si no se aportan, los campos correspondientes de cada
    perfil quedan en `None`/`[]`/`False` explícitamente — nunca se
    simulan ni se infieren.
    """
    warnings: list = []

    ageb_gdf, long_cluster, long_sector, agg_report = build_ageb_universe(
        warehouse_gdf, cluster_artifact, sector_names, id_col=id_col, sector_col=sector_col
    )
    if agg_report.n_agebs_sin_perfil:
        warnings.append(
            f"{agg_report.n_agebs_sin_perfil} AGEB(s) del warehouse quedaron sin perfil "
            "(todos sus sectores sin mapeo Louvain)."
        )
    if agg_report.sectores_no_mapeados:
        warnings.append(f"sectores sin comunidad Louvain asignada: {agg_report.sectores_no_mapeados}")

    relationships = build_territorial_relationships(
        ageb_gdf, long_sector, spatial_matrix=spatial_matrix, id_col=id_col, sector_col=sector_col
    )

    ageb_profiles = _build_ageb_profiles(
        ageb_gdf, long_sector, relationships, cluster_artifact, simulation_gdf, spatial_matrix, id_col, sector_col
    )
    municipality_profiles = _build_municipality_profiles(ageb_profiles, top_n_principales)
    community_profiles = _build_community_profiles(ageb_profiles, cluster_artifact, sector_names, top_n_principales)

    insights = {
        "portfolio": portfolio_insights(list(community_profiles.values())),
        "comunidades": {
            cl_key: community_insights(cp) for cl_key, cp in community_profiles.items()
        },
        "municipios": {
            muni: municipality_insights(mp) for muni, mp in municipality_profiles.items()
        },
        "agebs": {
            ageb: ageb_insights(profile) for ageb, profile in ageb_profiles.items()
        },
    }

    report = DecisionSupportReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        n_agebs=len(ageb_profiles),
        n_municipios=len(municipality_profiles),
        n_comunidades=len(community_profiles),
        has_simulation=simulation_gdf is not None,
        has_spatial_matrix=spatial_matrix is not None,
        ageb_profiles={k: v.to_dict() for k, v in ageb_profiles.items()},
        municipality_profiles={k: v.to_dict() for k, v in municipality_profiles.items()},
        community_profiles={k: v.to_dict() for k, v in community_profiles.items()},
        relationships=relationships.to_dict(),
        insights=insights,
        aggregation_report=agg_report.to_dict(),
        warnings=warnings,
    )
    logger.info("\n%s", report.summary())
    return report


__all__ = ["DecisionSupportReport", "build_decision_support_report"]
