"""Contratos del bundle externo de artefactos de ejecución."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from bootstrap_artifacts import REQUIRED, artifacts_ready, bootstrap, sha256_file
from package_artifacts import INCLUDED_DIRECTORIES, build_bundle


def _write_required_artifacts(root: Path) -> None:
    for relative in REQUIRED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    # El bundle debe incluir todos los directorios declarados, incluso si no
    # forman parte del conjunto mínimo de readiness.
    for relative_dir in INCLUDED_DIRECTORIES:
        directory = root / relative_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "fixture.txt").write_text("fixture", encoding="utf-8")


def test_bundle_round_trip_is_verified_and_externalizable(tmp_path):
    source = tmp_path / "source"
    _write_required_artifacts(source)
    bundle = tmp_path / "lattise-artifacts.zip"

    expected_checksum = build_bundle(source, bundle)
    assert expected_checksum == sha256_file(bundle)

    destination = tmp_path / "runtime-artifacts"
    bootstrap(destination, bundle.as_uri(), expected_checksum)

    assert artifacts_ready(destination)
    assert (destination / "serio/data/meta.json").read_bytes() == b"fixture"


def test_bundle_rejects_a_checksum_that_does_not_match(tmp_path):
    source = tmp_path / "source"
    _write_required_artifacts(source)
    bundle = tmp_path / "lattise-artifacts.zip"
    build_bundle(source, bundle)

    with pytest.raises(ValueError, match="SHA-256"):
        bootstrap(tmp_path / "runtime-artifacts", bundle.as_uri(), "0" * 64)
