# spatial/decision_support/__init__.py
"""
Decision Support Engine.

Organiza, sin recalcular nada, todo lo que el motor ya sabe de cada
AGEB/municipio/comunidad económica en perfiles territoriales
reutilizables. No toma decisiones, no recomienda, no optimiza, no
clasifica con IA — ver el encabezado de `spatial.decision_support.report`
para el contrato completo.

Uso típico:

    from spatial.decision_support import (
        build_decision_support_report,
        load_cluster_artifact,
        load_warehouse_gdf,
        load_sector_names,
        load_spatial_matrix,
    )

    report = build_decision_support_report(
        warehouse_gdf=load_warehouse_gdf(),
        cluster_artifact=load_cluster_artifact(),
        sector_names=load_sector_names(),
        spatial_matrix=load_spatial_matrix(gal_path, metadata_path),
        simulation_gdf=st.session_state.get("simulation_gdf"),   # opcional
    )
    report.to_json("data/decision_support/report.json")
"""
from spatial.decision_support.loader import (
    load_cluster_artifact,
    load_sector_names,
    load_spatial_matrix,
    load_warehouse_gdf,
)
from spatial.decision_support.profiles import AGEBProfile, CommunityProfile, MunicipalityProfile
from spatial.decision_support.relationships import TerritorialRelationships, build_territorial_relationships
from spatial.decision_support.report import DecisionSupportReport, build_decision_support_report

__all__ = [
    "AGEBProfile",
    "MunicipalityProfile",
    "CommunityProfile",
    "TerritorialRelationships",
    "build_territorial_relationships",
    "DecisionSupportReport",
    "build_decision_support_report",
    "load_cluster_artifact",
    "load_warehouse_gdf",
    "load_sector_names",
    "load_spatial_matrix",
]
