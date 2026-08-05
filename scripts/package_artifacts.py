"""Construye un ZIP versionado de los artefactos de ejecución.

No incluye insumos crudos ni salidas temporales. Después de publicarlo en R2
o en un CDN, copie el SHA-256 mostrado a ``LATTISE_ARTIFACT_BUNDLE_SHA256``.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

from bootstrap_artifacts import REQUIRED, artifacts_ready, sha256_file

INCLUDED_DIRECTORIES = (
    "data/warehouse",
    "data/analytics",
    "data/graph",
    "serio/data",
)


def build_bundle(source_root: Path, output_path: Path) -> str:
    source_root = source_root.resolve()
    if not artifacts_ready(source_root):
        missing = [item for item in REQUIRED if not (source_root / item).is_file()]
        raise ValueError(f"Faltan artefactos requeridos: {', '.join(missing)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_dir in INCLUDED_DIRECTORIES:
            directory = source_root / relative_dir
            for path in sorted(p for p in directory.rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(source_root).as_posix())
    return sha256_file(output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    checksum = build_bundle(args.source, args.output)
    print(f"Bundle: {args.output}")
    print(f"SHA256: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
