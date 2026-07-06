# spatial/simulation/matrix.py
"""
SpatialMatrix — Reconstrucción y validación de la matriz espacial M
(Especificación Formal v3.0, Sección 8, Stage 8 — Spatial Econometric
Engine / SEE).

Responsabilidad (Incremento 1):
    Reconstruir, a partir del artefacto ya persistido `graph.gal` (escrito
    por `spatial.graph.network.SpatialGraph.to_gal()`, Spatial Graph
    Builder — CERRADO), la matriz de pesos espaciales W fila-estandarizada
    que el operador `(I − ρW)^-1` usará en un incremento posterior.

Este módulo:
    - NO importa ni invoca `spatial.graph.network.SpatialGraphBuilder`.
      No reconstruye el grafo desde geometrías AGEB — es un consumidor
      puro del `.gal` ya escrito, igual que `allocation.weights` es un
      consumidor puro de `warehouse.parquet` (mismo criterio de Layer
      Isolation y Explicit Data Contracts, Sección 5).
    - NO calcula `(I − ρW)^-1`, NO recibe `ρ`, NO lee `shock_ageb.parquet`.
      Eso pertenece a un incremento posterior del SEE.
    - NO modifica ni depende de `spatial.allocation.simulation` (donde
      vivirá el operador completo).
    - Reporta explícitamente cualquier inconsistencia estructural del
      `.gal` (nodos duplicados, vecinos inexistentes, filas cuya suma no
      es ni 0 ni 1) — nunca la infiere ni la oculta en silencio.

Depende de (solo como consumidor de su artefacto, no como caller):
    - spatial.graph.network.SpatialGraph.to_gal() / to_graph_files()   (Spatial Graph Builder — LISTO)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from spatial.config import GRAPH_GAL_PATH, GRAPH_METADATA_JSON

logger = logging.getLogger("sew.simulation.matrix")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

_ROW_SUM_TOL = 1e-9


# ══════════════════════════════════════════════════════════════════════════
# Reporte de reconstrucción de W — mismo patrón que GraphReport/AllocationReport
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SpatialMatrixReport:
    n_nodos: int
    n_islas: int = 0
    islas: list = field(default_factory=list)
    grado_promedio: float = 0.0
    grado_min: int = 0
    grado_max: int = 0
    criterio: Optional[str] = None
    metadata_encontrada: bool = False
    filas_no_estocasticas: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        criterio_txt = self.criterio if self.criterio is not None else "desconocido (sin graph_metadata.json)"
        lines = [
            f"Spatial Matrix Report — {self.n_nodos} nodos, criterio '{criterio_txt}'",
            f"  grado promedio: {self.grado_promedio:.4f} (min={self.grado_min}, max={self.grado_max})",
        ]
        if self.islas:
            lines.append(
                f"  ⚠ {self.n_islas} isla(s) — fila de W en ceros (sin vecinos): {self.islas}"
            )
        else:
            lines.append("  sin islas.")
        if self.filas_no_estocasticas:
            lines.append(
                f"  ⚠ {len(self.filas_no_estocasticas)} fila(s) de W cuya suma no es ni 0 ni 1 "
                f"(tolerancia {_ROW_SUM_TOL}): {self.filas_no_estocasticas}"
            )
        else:
            lines.append("  todas las filas de W son válidas (suman 0 o 1).")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Lector puro de .gal — simétrico a SpatialGraph.to_gal() (graph/network.py)
# ══════════════════════════════════════════════════════════════════════════
def load_gal(path: str | Path) -> tuple[str, list[str], dict[str, list[str]]]:
    """
    Parsea un archivo `.gal` escrito por `SpatialGraph.to_gal()` sin volver
    a construir el grafo (no toca geometrías AGEB). Formato esperado
    (idéntico al escrito por graph/network.py):

        0 <n_nodos> spatial_graph <id_col>
        <id_nodo_1> <grado_1>
        <vecino_1_1> <vecino_1_2> ... (línea vacía si grado_1 == 0)
        <id_nodo_2> <grado_2>
        ...

    Devuelve (id_col, ids, neighbors):
        id_col     : nombre de la columna id declarado en el encabezado.
        ids        : orden EXACTO de nodos tal como aparece en el archivo
                     — este orden es el que indexará filas/columnas de W.
        neighbors  : {id_nodo: [vecino_1, vecino_2, ...]}, mismo contenido
                     que `SpatialGraph.neighbors` antes de serializar.

    Lanza `ValueError` ante cualquier inconsistencia estructural (encabezado
    inválido, grado declarado que no coincide con los vecinos listados,
    nodos duplicados, archivo truncado) — nunca repara ni infiere en
    silencio.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró '{path}'. Ejecuta SpatialGraphBuilder.build() + "
            "to_graph_files() (Spatial Graph Builder) primero."
        )

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"'{path}' está vacío — no es un .gal válido.")

    header = lines[0].split()
    if len(header) < 4:
        raise ValueError(f"Encabezado .gal inválido en '{path}': '{lines[0]}'")
    try:
        n_declarado = int(header[1])
    except ValueError as exc:
        raise ValueError(f"Encabezado .gal inválido en '{path}': '{lines[0]}'") from exc
    id_col = header[3]

    ids: list[str] = []
    neighbors: dict[str, list[str]] = {}
    i = 1
    while i < len(lines):
        node_header = lines[i].split()
        if len(node_header) != 2:
            raise ValueError(
                f"Línea de nodo mal formada en '{path}' (línea {i + 1}): '{lines[i]}'"
            )
        node_id, degree_str = node_header
        try:
            degree = int(degree_str)
        except ValueError as exc:
            raise ValueError(
                f"Grado no numérico para '{node_id}' en '{path}' (línea {i + 1}): '{lines[i]}'"
            ) from exc

        i += 1
        if i >= len(lines):
            raise ValueError(f"'{path}' truncado: falta la línea de vecinos para '{node_id}'.")

        vecinos_raw = lines[i].strip()
        vecinos = vecinos_raw.split() if vecinos_raw else []
        if len(vecinos) != degree:
            raise ValueError(
                f"Grado declarado ({degree}) no coincide con el número de vecinos listados "
                f"({len(vecinos)}) para '{node_id}' en '{path}'."
            )

        if node_id in neighbors:
            raise ValueError(f"'{path}' tiene el identificador duplicado '{node_id}'.")

        ids.append(node_id)
        neighbors[node_id] = vecinos
        i += 1

    if len(ids) != n_declarado:
        raise ValueError(
            f"'{path}' declara {n_declarado} nodos en el encabezado pero contiene {len(ids)}."
        )

    id_set = set(ids)
    for node_id, vecinos in neighbors.items():
        desconocidos = [v for v in vecinos if v not in id_set]
        if desconocidos:
            raise ValueError(
                f"'{node_id}' en '{path}' referencia vecino(s) inexistente(s) en el archivo: "
                f"{desconocidos[:10]}"
            )

    return id_col, ids, neighbors


# ══════════════════════════════════════════════════════════════════════════
# Construcción de W fila-estandarizada — sin ρ, sin inversión (Incremento 1)
# ══════════════════════════════════════════════════════════════════════════
def _build_row_standardized_matrix(ids: list[str], neighbors: dict[str, list[str]]) -> np.ndarray:
    """
    W[i, j] = 1 / grado(i) si j es vecino de i, 0 en cualquier otro caso
    (incluida la diagonal). Filas isla (grado 0) quedan íntegramente en
    cero — nunca se fuerza un vecino artificial ni una fila uniforme.
    """
    n = len(ids)
    index = {cvegeo: pos for pos, cvegeo in enumerate(ids)}
    W = np.zeros((n, n), dtype=np.float64)

    for cvegeo, vecinos in neighbors.items():
        i = index[cvegeo]
        grado = len(vecinos)
        if grado == 0:
            continue
        peso = 1.0 / grado
        for vecino in vecinos:
            j = index[vecino]
            W[i, j] = peso

    return W


def _validate_row_stochastic(W: np.ndarray, ids: list[str], tol: float = _ROW_SUM_TOL) -> list[str]:
    """
    Verifica que cada fila de W sume exactamente 0 (isla) o 1 (fila-
    estandarizada). Devuelve la lista de `cvegeo` cuyas filas no cumplen
    ninguno de los dos casos — nunca corrige la fila, solo la reporta.
    """
    row_sums = W.sum(axis=1)
    invalidas = []
    for cvegeo, s in zip(ids, row_sums):
        if abs(s) > tol and abs(s - 1.0) > tol:
            invalidas.append(cvegeo)
    return invalidas


# ══════════════════════════════════════════════════════════════════════════
# SpatialMatrix — envoltorio validado de W + metadatos de trazabilidad
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SpatialMatrix:
    """
    Matriz espacial M (fila-estandarizada) reconstruida desde `graph.gal`,
    junto con el orden explícito de `cvegeo` que indexa sus filas/columnas
    y su reporte de validación. Es la única infraestructura de este
    incremento: NO expone `(I − ρW)^-1` ni ningún parámetro ρ.
    """
    id_col: str
    ids: list
    neighbors: dict
    W: np.ndarray
    criterio: Optional[str]
    report: SpatialMatrixReport

    def index_of(self, cvegeo) -> int:
        """Posición de `cvegeo` en `ids` (y por tanto en filas/columnas de W)."""
        try:
            return self.ids.index(cvegeo)
        except ValueError as exc:
            raise KeyError(f"'{cvegeo}' no pertenece a esta SpatialMatrix.") from exc

    def neighbors_of(self, cvegeo) -> list:
        if cvegeo not in self.neighbors:
            raise KeyError(f"'{cvegeo}' no pertenece a esta SpatialMatrix.")
        return list(self.neighbors[cvegeo])

    def is_island(self, cvegeo) -> bool:
        return len(self.neighbors_of(cvegeo)) == 0

    def row(self, cvegeo) -> np.ndarray:
        """Fila de W correspondiente a `cvegeo` (vector de pesos hacia sus vecinos)."""
        return self.W[self.index_of(cvegeo)].copy()

    def to_frame(self) -> pd.DataFrame:
        """W como DataFrame etiquetado por `cvegeo` en filas y columnas (solo inspección)."""
        return pd.DataFrame(self.W, index=self.ids, columns=self.ids)

    @classmethod
    def from_gal(
        cls,
        gal_path: str | Path = GRAPH_GAL_PATH,
        metadata_path: Optional[str | Path] = GRAPH_METADATA_JSON,
        tol: float = _ROW_SUM_TOL,
    ) -> "SpatialMatrix":
        """
        Pipeline completo del Incremento 1: lee `graph.gal` (Spatial Graph
        Builder, cerrado), reconstruye W fila-estandarizada, la valida, y
        adjunta `criterio` (queen/rook) desde `graph_metadata.json` si está
        disponible — sin recalcular nada del grafo en sí.

        Si `metadata_path` no existe o es `None`, `criterio` queda en
        `None` explícitamente (nunca se infiere) y se deja constancia en
        el reporte (`metadata_encontrada=False`).
        """
        id_col, ids, neighbors = load_gal(gal_path)
        W = _build_row_standardized_matrix(ids, neighbors)
        filas_invalidas = _validate_row_stochastic(W, ids, tol=tol)

        grados = [len(neighbors[cvegeo]) for cvegeo in ids]
        islas = sorted(cvegeo for cvegeo in ids if len(neighbors[cvegeo]) == 0)

        criterio: Optional[str] = None
        metadata_encontrada = False
        if metadata_path is not None:
            metadata_path = Path(metadata_path)
            if metadata_path.exists():
                metadata_encontrada = True
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                criterio = meta.get("criterio")
            else:
                logger.warning(
                    "No se encontró '%s' — SpatialMatrix.criterio quedará en None "
                    "(no se infiere el criterio de contigüidad).",
                    metadata_path,
                )

        report = SpatialMatrixReport(
            n_nodos=len(ids),
            n_islas=len(islas),
            islas=islas,
            grado_promedio=float(np.mean(grados)) if grados else 0.0,
            grado_min=int(min(grados)) if grados else 0,
            grado_max=int(max(grados)) if grados else 0,
            criterio=criterio,
            metadata_encontrada=metadata_encontrada,
            filas_no_estocasticas=filas_invalidas,
        )
        logger.info("\n%s", report.summary())

        return cls(
            id_col=id_col,
            ids=ids,
            neighbors=neighbors,
            W=W,
            criterio=criterio,
            report=report,
        )