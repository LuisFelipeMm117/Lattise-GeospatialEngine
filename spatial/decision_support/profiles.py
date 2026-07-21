# spatial/decision_support/profiles.py
"""
Decision Support Engine — Perfiles territoriales.

Define las tres unidades de observación del Decision Support Engine:
`AGEBProfile`, `MunicipalityProfile` y `CommunityProfile`. Cada una es
un `dataclass` serializable (`to_dict()`), exactamente el mismo patrón
usado en todo el motor (`AllocationReport`, `SimulationReport`,
`SpatialMatrixReport`, ...) — nunca calculan nada por sí mismas, solo
empaquetan valores ya calculados en `spatial.decision_support.aggregation`
/ `spatial.decision_support.relationships`.

Ningún campo aquí es un score, una recomendación ni una inferencia:
son exclusivamente lecturas organizadas de columnas ya existentes en
`warehouse.parquet`, `sector_cluster.json`, `simulation_gdf` y
`SpatialMatrix` — ver encabezado de `spatial/decision_support/report.py`
para el contrato completo de entradas.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class AGEBProfile:
    """Perfil territorial de un único AGEB.

    Campos de impacto (`impacto_directo`, `impacto_indirecto`,
    `impacto_propagado`) quedan en `None` explícitamente cuando no hay
    `simulation_gdf` disponible — nunca se sustituyen por 0 (0 sería un
    valor económico real y falso; `None` significa "no simulado").
    """
    # ── Identidad ────────────────────────────────────────────────────
    ageb: str
    municipio: str
    entidad: Optional[str] = None

    # ── Comunidad económica (Louvain, `sector_cluster.json`) ───────────
    cluster_id: Optional[int] = None
    cluster_nombre: Optional[str] = None
    cluster_peso: Optional[float] = None
    peso_metodo: Optional[str] = None

    # ── Estructura sectorial (`warehouse.parquet`) ──────────────────────
    sector_dominante: Optional[str] = None
    sector_dominante_nombre: Optional[str] = None
    sector_dominante_peso: Optional[float] = None
    n_sectores: int = 0
    sectores_presentes: list = field(default_factory=list)

    # ── Participación económica territorial ─────────────────────────────
    peso_total: float = 0.0
    participacion_pct: float = 0.0
    ranking: Optional[int] = None
    n_agebs_universo: int = 0

    # ── Impacto de simulación (Stage 8C, OPCIONAL) ──────────────────────
    impacto_directo: Optional[float] = None
    impacto_indirecto: Optional[float] = None
    impacto_propagado: Optional[float] = None

    # ── Contigüidad espacial (Spatial Graph Builder, CERRADO) ───────────
    n_vecinos: int = 0
    agebs_relacionadas: list = field(default_factory=list)
    municipios_conectados: list = field(default_factory=list)
    comunidades_relacionadas: list = field(default_factory=list)
    es_isla: Optional[bool] = None
    cobertura_espacial: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MunicipalityProfile:
    """Perfil agregado de un municipio (agregación de `AGEBProfile`)."""
    municipio: str
    agebs: list = field(default_factory=list)
    n_agebs: int = 0
    clusters_presentes: list = field(default_factory=list)
    sectores_presentes: list = field(default_factory=list)
    peso_total: float = 0.0
    participacion_pct: float = 0.0

    impacto_directo_agregado: Optional[float] = None
    impacto_indirecto_agregado: Optional[float] = None
    impacto_propagado_agregado: Optional[float] = None
    impacto_propagado_promedio: Optional[float] = None

    agebs_principales: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommunityProfile:
    """Perfil agregado de una comunidad económica (cluster Louvain)."""
    cluster_id: int
    nombre: str
    n_agebs: int = 0
    n_municipios: int = 0
    sectores: list = field(default_factory=list)
    sectores_nombres: list = field(default_factory=list)
    n_sectores: int = 0
    centralidad_media: Optional[float] = None
    bl_media: Optional[float] = None
    fl_media: Optional[float] = None
    peso_total: float = 0.0
    participacion_pct: float = 0.0
    # ── Peso granular — ver spatial/decision_support/aggregation.py::
    # community_granular_weights(). A diferencia de `peso_total` (que
    # atribuye el peso COMPLETO de cada AGEB a su comunidad dominante),
    # `peso_granular` reparte el peso de cada AGEB exactamente donde
    # corresponde, sumando directo desde AGEB x comunidad. Es el campo
    # recomendado para cualquier agregado que se presente como "peso
    # económico de la comunidad" — ver auditoría de Lattise Studio.
    peso_granular: float = 0.0
    participacion_pct_granular: float = 0.0
    municipios_principales: list = field(default_factory=list)
    agebs_principales: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = ["AGEBProfile", "MunicipalityProfile", "CommunityProfile"]
