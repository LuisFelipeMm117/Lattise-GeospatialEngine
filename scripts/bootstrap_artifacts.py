"""Descarga y verifica el bundle inmutable de artefactos de Lattise.

Uso de producción::

    LATTISE_ARTIFACTS_DIR=/var/lib/lattise/artifacts \
    LATTISE_ARTIFACT_BUNDLE_URL=https://<R2-o-CDN>/lattise-artifacts-v1.zip \
    LATTISE_ARTIFACT_BUNDLE_SHA256=<sha256> \
    python scripts/bootstrap_artifacts.py

El ZIP debe contener ``data/`` y ``serio/data/`` en su raíz. Si los
artefactos requeridos ya existen, el script no descarga nada. La extracción
se hace en un directorio temporal y se publica al final, para no dejar un
estado parcialmente escrito si falla la red o la verificación.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REQUIRED = (
    "data/warehouse/warehouse.parquet",
    "data/analytics/sector_cluster.json",
    "data/graph/graph.gal",
    "data/graph/graph_metadata.json",
    "serio/data/meta.json",
    "serio/data/sectores.csv",
)


def _root_from_env() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("LATTISE_ARTIFACTS_DIR", repo_root)).expanduser()


def artifacts_ready(root: Path) -> bool:
    return all((root / relative).is_file() for relative in REQUIRED)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_safely(bundle: Path, destination: Path) -> None:
    with zipfile.ZipFile(bundle) as archive:
        root = destination.resolve()
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"El bundle contiene una ruta no segura: {member.filename!r}")
        archive.extractall(destination)


def bootstrap(root: Path, url: str, expected_sha256: str) -> None:
    if artifacts_ready(root):
        print(f"Artefactos ya disponibles en {root}.")
        return
    if not expected_sha256 or len(expected_sha256) != 64:
        raise ValueError("LATTISE_ARTIFACT_BUNDLE_SHA256 es obligatorio y debe ser un SHA-256 hexadecimal.")

    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lattise-artifacts-", dir=root.parent) as temp_dir:
        temp = Path(temp_dir)
        bundle = temp / "artifacts.zip"
        print("Descargando bundle de artefactos...")
        urllib.request.urlretrieve(url, bundle)
        actual_sha256 = sha256_file(bundle)
        if actual_sha256.lower() != expected_sha256.lower():
            raise ValueError("El SHA-256 del bundle no coincide; no se publicaron los artefactos.")

        unpacked = temp / "unpacked"
        unpacked.mkdir()
        _extract_safely(bundle, unpacked)
        if not artifacts_ready(unpacked):
            raise ValueError("El bundle no contiene todos los artefactos requeridos.")

        staging = root.parent / f".{root.name}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.move(str(unpacked), staging)
        if root.exists():
            shutil.rmtree(root)
        staging.replace(root)
    print(f"Artefactos verificados y disponibles en {root}.")


def main() -> int:
    root = _root_from_env()
    if artifacts_ready(root):
        print(f"Artefactos ya disponibles en {root}.")
        return 0
    url = os.environ.get("LATTISE_ARTIFACT_BUNDLE_URL", "").strip()
    checksum = os.environ.get("LATTISE_ARTIFACT_BUNDLE_SHA256", "").strip()
    if not url:
        print(
            "Faltan artefactos y LATTISE_ARTIFACT_BUNDLE_URL no está configurada. "
            "Defina una URL firmada o de CDN y su SHA-256.",
            file=sys.stderr,
        )
        return 2
    bootstrap(root, url, checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
