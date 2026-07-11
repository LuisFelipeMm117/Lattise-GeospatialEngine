#!/usr/bin/env python3
# scripts/build_sector_clusters.py
"""
Genera el artefacto congelado `data/analytics/sector_cluster.json`:
la asignación estática sector SERIO → comunidad económica (Louvain),
derivada UNA sola vez de la matriz de coeficientes técnicos nacional
`A_nacional.npy`.

    A_nacional.npy  (insumo congelado, serio/data/, jamás editado)
      ↓  L = (I − A)⁻¹                          (Leontief)
      ↓  encadenamientos (BL, FL) + centralidad
      ↓  grafo de similitud de columnas de L (top-k + umbral)
      ↓  community_louvain.best_partition()
    data/analytics/sector_cluster.json   (artefacto nuevo, congelado)

Este script:
    - NO modifica spatial/, serio/, tests/ ni examples/ — únicamente
      LEE `serio/data/A_nacional.npy` y `serio/data/sectores.csv`
      (activos ya congelados, Stage SERIO) e importa `spatial.config`
      solo para resolver rutas (lectura de constantes, no escritura).
    - NO se ejecuta en cada corrida de la app — es un paso de
      preparación de datos offline, igual que
      `scripts/build_crosswalk_maestro.py`. Lattise Studio nunca
      recalcula Louvain: la nueva página `Spatial Cluster Intelligence`
      solo LEE el JSON que este script produce.
    - Reproducible: `random_state`/`seed` fijos (42). Volver a correrlo
      con la misma A_nacional.npy y los mismos parámetros produce el
      mismo artefacto byte a byte (salvo el timestamp).
    - Nomenclatura de comunidades 100% basada en reglas determinísticas
      sobre datos ya calculados (sector de mayor centralidad del
      cluster) — no usa IA ni modelos generativos.

Uso:
    python -m scripts.build_sector_clusters
    python -m scripts.build_sector_clusters --resolution 1.2 --top-k 12
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spatial.config import DATA_DIR  # noqa: E402 — solo lectura de constante de ruta

try:
    import networkx as nx
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Falta 'networkx'. Instala con: pip install networkx --break-system-packages"
    ) from e

try:
    import community.community_louvain as community_louvain
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Falta 'python-louvain'. Instala con: pip install python-louvain --break-system-packages"
    ) from e

# ── Rutas ────────────────────────────────────────────────────────────────
A_NACIONAL_NPY = _REPO_ROOT / "serio" / "data" / "A_nacional.npy"
SECTORES_CSV = _REPO_ROOT / "serio" / "data" / "sectores.csv"
ANALYTICS_DIR = DATA_DIR / "analytics"
SECTOR_CLUSTER_JSON = ANALYTICS_DIR / "sector_cluster.json"

DEFAULT_TOP_K = 8
DEFAULT_THRESHOLD = 0.0005
DEFAULT_RESOLUTION = 0.15
SEED = 42


# ── Núcleo matemático (idéntico en método al Módulo 1 de Cluster ──────────
#    Intelligence — Leontief + Louvain — pero ejecutado una sola vez aquí,
#    nunca en tiempo de request de la app) ─────────────────────────────────
def _build_partition(A: np.ndarray, top_k: int, threshold: float, resolution: float) -> dict:
    n = A.shape[0]
    I = np.eye(n)
    M = I - A
    L = np.linalg.inv(M)

    bl_raw = L.sum(axis=0)
    fl_raw = L.sum(axis=1)
    bl = bl_raw / bl_raw.mean()
    fl = fl_raw / fl_raw.mean()

    col_sum = L.sum(axis=0, keepdims=True)
    col_sum[col_sum == 0] = 1
    W = L / col_sum
    W_sym = (W + W.T) / 2

    W_f = np.zeros_like(W_sym)
    for i in range(n):
        idx = np.argsort(W_sym[i])[-top_k:]
        W_f[i, idx] = W_sym[i, idx]
    W_f[W_f < threshold] = 0

    G_full = nx.from_numpy_array(W_f)
    G_full.remove_nodes_from(list(nx.isolates(G_full)))
    if G_full.number_of_nodes() == 0:
        raise RuntimeError(
            "El grafo de similitud quedó vacío tras aplicar top_k/threshold. "
            "Reduce --threshold o aumenta --top-k."
        )
    largest_cc = max(nx.connected_components(G_full), key=len)
    G = G_full.subgraph(largest_cc).copy()

    partition = community_louvain.best_partition(G, resolution=resolution, random_state=SEED)
    modularity = community_louvain.modularity(partition, G)

    try:
        centrality = nx.eigenvector_centrality(G, max_iter=1000, tol=1e-6)
    except nx.PowerIterationFailedConvergence:
        centrality = nx.degree_centrality(G)

    return {
        "n_total": n,
        "n_in_graph": G.number_of_nodes(),
        "n_isolated": n - G_full.number_of_nodes(),
        "n_minor_component": G_full.number_of_nodes() - G.number_of_nodes(),
        "partition": partition,   # nodo (índice 0..n-1) → cluster_id
        "modularity": float(modularity),
        "centrality": centrality,
        "bl": bl,
        "fl": fl,
    }


def _nombre_cluster(cluster_id: int, miembros: list[dict]) -> str:
    """Regla determinística, sin IA: nombra la comunidad según el sector
    de mayor centralidad dentro de ella. Si hay empate, usa el primero
    en orden de índice (determinístico)."""
    lider = max(miembros, key=lambda m: (m["centralidad"], -m["indice"]))
    return f"Comunidad {cluster_id} — {lider['nombre']}"


def build_artifact(top_k: int, threshold: float, resolution: float) -> dict[str, Any]:
    if not A_NACIONAL_NPY.exists():
        raise FileNotFoundError(f"No se encontró {A_NACIONAL_NPY} (insumo congelado SERIO).")
    if not SECTORES_CSV.exists():
        raise FileNotFoundError(f"No se encontró {SECTORES_CSV} (insumo congelado SERIO).")

    A = np.load(A_NACIONAL_NPY)
    df_sec = pd.read_csv(SECTORES_CSV)
    if len(df_sec) != A.shape[0]:
        raise ValueError(
            f"sectores.csv tiene {len(df_sec)} filas pero A_nacional.npy es "
            f"{A.shape[0]}x{A.shape[0]}. No se infiere una correspondencia parcial."
        )
    codigos = df_sec["scian"].astype(str).tolist()   # código SERIO (78 sectores)
    nombres = df_sec["nombre"].astype(str).tolist()

    t0 = time.perf_counter()
    r = _build_partition(A, top_k=top_k, threshold=threshold, resolution=resolution)
    elapsed = time.perf_counter() - t0

    clusters: dict[str, dict] = {}
    sector_to_cluster: dict[str, int] = {}
    sector_centrality: dict[str, float] = {}
    sector_bl: dict[str, float] = {}
    sector_fl: dict[str, float] = {}
    sectores_sin_cluster: list[str] = []

    for idx in range(r["n_total"]):
        codigo = codigos[idx]
        sector_bl[codigo] = round(float(r["bl"][idx]), 6)
        sector_fl[codigo] = round(float(r["fl"][idx]), 6)
        if idx not in r["partition"]:
            sectores_sin_cluster.append(codigo)
            continue
        cl = int(r["partition"][idx])
        cent = round(float(r["centrality"].get(idx, 0.0)), 6)
        sector_to_cluster[codigo] = cl
        sector_centrality[codigo] = cent
        clusters.setdefault(str(cl), {"cluster_id": cl, "miembros": []})
        clusters[str(cl)]["miembros"].append({
            "indice": idx, "codigo": codigo, "nombre": nombres[idx], "centralidad": cent,
        })

    for cl_key, cl_data in clusters.items():
        miembros = cl_data["miembros"]
        cl_data["nombre"] = _nombre_cluster(cl_data["cluster_id"], miembros)
        cl_data["sectores"] = sorted(m["codigo"] for m in miembros)
        cl_data["n_sectores"] = len(miembros)
        cl_data["centralidad_media"] = round(
            sum(m["centralidad"] for m in miembros) / len(miembros), 6
        )
        cl_data["bl_media"] = round(
            sum(sector_bl[m["codigo"]] for m in miembros) / len(miembros), 6
        )
        cl_data["fl_media"] = round(
            sum(sector_fl[m["codigo"]] for m in miembros) / len(miembros), 6
        )
        del cl_data["miembros"]

    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(A_NACIONAL_NPY.relative_to(_REPO_ROOT)),
        "method": "Leontief L=(I-A)^-1 → grafo de similitud de columnas (top_k+umbral) → Louvain",
        "params": {
            "top_k": top_k, "threshold": threshold, "resolution": resolution, "seed": SEED,
        },
        "n_sectores_total": r["n_total"],
        "n_sectores_en_grafo": r["n_in_graph"],
        "n_sectores_aislados": r["n_isolated"],
        "n_sectores_componente_menor": r["n_minor_component"],
        "n_clusters": len(clusters),
        "modularity": round(r["modularity"], 6),
        "tiempo_ejecucion_seg": round(elapsed, 4),
        "clusters": clusters,
        "sector_to_cluster": sector_to_cluster,
        "sector_centrality": sector_centrality,
        "sector_bl": sector_bl,
        "sector_fl": sector_fl,
        "sectores_sin_cluster": sectores_sin_cluster,
    }
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION)
    parser.add_argument("--out", type=Path, default=SECTOR_CLUSTER_JSON)
    args = parser.parse_args()

    artifact = build_artifact(args.top_k, args.threshold, args.resolution)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        out_display = args.out.relative_to(_REPO_ROOT)
    except ValueError:
        out_display = args.out
    print(f"✓ {out_display}")
    print(f"  sectores: {artifact['n_sectores_total']} total, "
          f"{artifact['n_sectores_en_grafo']} en grafo, "
          f"{artifact['n_sectores_aislados']} aislados")
    print(f"  clusters: {artifact['n_clusters']}  ·  modularidad Q={artifact['modularity']}")
    for cl in sorted(artifact["clusters"].values(), key=lambda c: -c["n_sectores"]):
        print(f"    · {cl['nombre']}  ({cl['n_sectores']} sectores)")
    if artifact["sectores_sin_cluster"]:
        print(f"  ⚠ sin cluster asignado ({len(artifact['sectores_sin_cluster'])}): "
              f"{artifact['sectores_sin_cluster']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
