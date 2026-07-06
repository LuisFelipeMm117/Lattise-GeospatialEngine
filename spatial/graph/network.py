# spatial/graph/network.py
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.strtree import STRtree

from spatial.config import AGEB_ID_COL, GRAPH_GAL_PATH, GRAPH_METADATA_JSON

logger = logging.getLogger("sew.graph.network")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

CRITERIOS_VALIDOS = ("queen", "rook")

_SHARED_EDGE_TOL = 1e-9


@dataclass
class GraphReport:
    criterio: str
    n_nodos: int
    n_aristas: int
    n_islas: int = 0
    islas: list = field(default_factory=list)
    grado_promedio: float = 0.0
    grado_min: int = 0
    grado_max: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        lines = [
            f"Spatial Graph Report — criterio '{self.criterio}', {self.n_nodos} nodos, "
            f"{self.n_aristas} aristas (no dirigidas)",
            f"  grado promedio: {self.grado_promedio:.4f} (min={self.grado_min}, max={self.grado_max})",
        ]
        if self.islas:
            lines.append(
                f"  ⚠ {self.n_islas} isla(s) — SIN vecinos bajo criterio '{self.criterio}' "
                f"(no se fuerza ningún vecino artificial): {self.islas}"
            )
        else:
            lines.append("  sin islas.")
        return "\n".join(lines)


@dataclass
class SpatialGraph:
    id_col: str
    criterio: str
    neighbors: dict
    report: GraphReport

    def neighbors_of(self, ageb_id) -> list:
        if ageb_id not in self.neighbors:
            raise KeyError(f"'{ageb_id}' no pertenece al grafo (no estaba en el GeoDataFrame de entrada).")
        return list(self.neighbors[ageb_id])

    def is_island(self, ageb_id) -> bool:
        return len(self.neighbors_of(ageb_id)) == 0

    def to_gal(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ids = list(self.neighbors.keys())
        lines = [f"0 {len(ids)} spatial_graph {self.id_col}"]
        for ageb_id in ids:
            vecinos = self.neighbors[ageb_id]
            lines.append(f"{ageb_id} {len(vecinos)}")
            lines.append(" ".join(str(v) for v in vecinos))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Grafo serializado en formato .gal: %s", path)
        return path


class SpatialGraphBuilder:
    def __init__(self, id_col: str = AGEB_ID_COL, criterio: str = "queen"):
        if criterio not in CRITERIOS_VALIDOS:
            raise ValueError(f"criterio debe ser uno de {CRITERIOS_VALIDOS}, se recibió '{criterio}'.")
        self.id_col = id_col
        self.criterio = criterio

    def build(self, ageb_gdf: gpd.GeoDataFrame) -> SpatialGraph:
        if self.id_col not in ageb_gdf.columns:
            raise ValueError(f"El GeoDataFrame no tiene la columna id '{self.id_col}'.")
        if ageb_gdf[self.id_col].duplicated().any():
            dupes = sorted(set(ageb_gdf.loc[ageb_gdf[self.id_col].duplicated(keep=False), self.id_col]))
            raise ValueError(
                f"'{self.id_col}' tiene valores duplicados — resuélvelo antes de construir el grafo. "
                f"Duplicados: {dupes[:10]}"
            )
        if ageb_gdf.geometry.isna().any():
            faltantes = ageb_gdf.loc[ageb_gdf.geometry.isna(), self.id_col].astype(str).tolist()
            raise ValueError(f"Geometría nula en {len(faltantes)} AGEB(s): {faltantes[:10]}")

        gdf = ageb_gdf.reset_index(drop=True)
        ids = gdf[self.id_col].astype(str).to_numpy()
        geoms = gdf.geometry.values

        tree = STRtree(geoms)
        neighbors: dict = {ageb_id: [] for ageb_id in ids}

        for i, geom in enumerate(geoms):
            candidate_idx = tree.query(geom, predicate="touches")
            for j in candidate_idx:
                j = int(j)
                if j == i:
                    continue
                if self.criterio == "rook":
                    shared = geom.intersection(geoms[j])
                    if shared.length <= _SHARED_EDGE_TOL:
                        continue
                neighbors[ids[i]].append(ids[j])

        for ageb_id in neighbors:
            neighbors[ageb_id] = sorted(set(neighbors[ageb_id]))

        grados = [len(v) for v in neighbors.values()]
        islas = sorted(ageb_id for ageb_id, v in neighbors.items() if len(v) == 0)
        n_aristas = sum(grados) // 2

        report = GraphReport(
            criterio=self.criterio,
            n_nodos=len(ids),
            n_aristas=n_aristas,
            n_islas=len(islas),
            islas=islas,
            grado_promedio=float(np.mean(grados)) if grados else 0.0,
            grado_min=int(min(grados)) if grados else 0,
            grado_max=int(max(grados)) if grados else 0,
        )
        logger.info("\n%s", report.summary())
        return SpatialGraph(id_col=self.id_col, criterio=self.criterio, neighbors=neighbors, report=report)

    def to_graph_files(
        self,
        graph: SpatialGraph,
        gal_path: str | Path = GRAPH_GAL_PATH,
        metadata_path: str | Path = GRAPH_METADATA_JSON,
    ) -> tuple[Path, Path]:
        gal_path = graph.to_gal(gal_path)
        metadata_path = Path(metadata_path)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(
                {
                    "id_col": graph.id_col,
                    "criterio": graph.criterio,
                    "report": graph.report.to_dict(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.info("Metadata del grafo serializada: %s", metadata_path)
        return gal_path, metadata_path


def load_graph_metadata(metadata_path: str | Path = GRAPH_METADATA_JSON) -> dict:
    path = Path(metadata_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró graph_metadata.json en '{path}'. Ejecuta "
            "SpatialGraphBuilder.build() + to_graph_files() primero."
        )
    return json.loads(path.read_text(encoding="utf-8"))