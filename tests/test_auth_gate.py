"""Regresión del modo de autenticación temporal para pruebas."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.helpers.auth_gate import _auth_mode, _test_user


def test_auth_mode_explicit_supabase_is_preserved(monkeypatch):
    # El entorno debe prevalecer sobre un secrets.toml local de desarrollo.
    monkeypatch.setenv("LATTISE_AUTH_MODE", "supabase")
    assert _auth_mode() == "supabase"


def test_auth_mode_allows_explicit_testing_bypass(monkeypatch):
    monkeypatch.setenv("LATTISE_AUTH_MODE", "disabled")
    monkeypatch.setenv("LATTISE_TEST_USER_EMAIL", "pruebas@lattise.local")
    assert _auth_mode() == "disabled"
    assert _test_user() == {"id": "local-testing-user", "email": "pruebas@lattise.local"}


def test_auth_mode_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("LATTISE_AUTH_MODE", "open")
    with pytest.raises(RuntimeError, match="LATTISE_AUTH_MODE"):
        _auth_mode()
