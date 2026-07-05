# tests/test_crosswalk_maestro.py
"""
Pruebas de integración del Crosswalk Maestro SCIAN → SERIO (v0.1):

    Crosswalk_Maestro_SCIAN_SERIO_v0.1.csv (MASTER_SCHEMA)
      ↓ crosswalk_maestro.build_authoring_csv_from_master()
    crosswalk_autoria_scian_serio.csv (AUTHORING_SCHEMA)
      ↓ CrosswalkBuilder.load_authoring() → validate_authoring()
      ↓ CrosswalkBuilder.compile_to_flat_lookup()
    crosswalk_compiled.csv (CROSSWALK_SCHEMA)
      ↓ CrosswalkBuilder.save_compiled_lookup()
      ↓ CrosswalkBuilder.validate() → build_lookup() → apply()   [contrato EXISTENTE, sin cambios]

Esta suite es independiente de tests/test_crosswalk.py y
tests/test_crosswalk_hierarchical.py: no reutiliza sus fixtures ni las
modifica, para no arriesgar ninguna prueba ya existente.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spatial.config import CROSSWALK_MASTER_RAW_CSV, SERIO_SECTORES_CSV
from spatial.warehouse.crosswalk import (
    AUTHORING_SCHEMA,
    AuthoringStatus,
    CROSSWALK_SCHEMA,
    CrosswalkBuilder,
    EvidenceType,
    MappingType,
)
from spatial.warehouse.crosswalk_maestro import (
    CrosswalkMaestroError,
    MASTER_SCHEMA,
    build_authoring_csv_from_master,
    convert_master_to_authoring,
    load_master_csv,
    load_serio_catalog,
)

# Universo SERIO reducido y sintético para las pruebas unitarias — igual
# espíritu que SERIO_SECTORS en test_crosswalk.py / test_crosswalk_hierarchical.py,
# pero como catálogo código→nombre (lo que consume este módulo).
_NAME_TO_CODE = {
    "Agricultura": "111",
    "Cría y explotación de animales": "112",
    "Industria alimentaria": "311",
    "Comercio al por mayor de abarrotes, alimentos, bebidas, hielo y tabaco": "431",
}
_SERIO_CODES = list(_NAME_TO_CODE.values())


def _master_row(**overrides) -> dict:
    base = {
        "nivel_scian": "subsector",
        "codigo_scian": "111",
        "descripcion_scian": "Agricultura",
        "sector_serio": "Agricultura",
        "confianza": "ALTA",
        "requiere_revision": "NO",
        "justificacion": "Coincidencia directa y exacta con el sector SERIO 111.",
    }
    base.update(overrides)
    return base


def _master_df(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=MASTER_SCHEMA)


# ════════════════════════════════════════════════════════════════════════
# Carga del Crosswalk Maestro crudo y del catálogo SERIO
# ════════════════════════════════════════════════════════════════════════
def test_load_master_csv_roundtrip(tmp_path):
    path = tmp_path / "maestro.csv"
    _master_df(_master_row(), _master_row(codigo_scian="112", sector_serio="Cría y explotación de animales")).to_csv(path, index=False)

    df = load_master_csv(path)
    assert list(df.columns) == MASTER_SCHEMA
    assert set(df["codigo_scian"]) == {"111", "112"}


def test_load_master_csv_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_master_csv(tmp_path / "no_existe.csv")


def test_load_master_csv_rejects_wrong_schema(tmp_path):
    path = tmp_path / "maestro_malo.csv"
    pd.DataFrame({"codigo": ["111"], "nombre": ["Agricultura"]}).to_csv(path, index=False)
    with pytest.raises(CrosswalkMaestroError):
        load_master_csv(path)


def test_load_serio_catalog_reads_real_sectores_csv():
    codes, name_to_code = load_serio_catalog(SERIO_SECTORES_CSV)
    assert len(codes) == 78
    assert len(set(codes)) == 78
    assert name_to_code["Agricultura"] == "111"


# ════════════════════════════════════════════════════════════════════════
# Traducción MASTER_SCHEMA → AUTHORING_SCHEMA (las 4 reglas soportadas)
# ════════════════════════════════════════════════════════════════════════
def test_convert_alta_no_produces_verified_exact_official():
    df = _master_df(_master_row())
    out = convert_master_to_authoring(df, _NAME_TO_CODE)
    assert list(out.columns) == AUTHORING_SCHEMA
    row = out.iloc[0]
    assert row["status"] == AuthoringStatus.VERIFIED.value
    assert row["mapping_type"] == MappingType.EXACT.value
    assert row["evidence_type"] == EvidenceType.OFFICIAL.value
    assert row["serio_sector"] == "111"
    assert row["serio_nombre"] == "Agricultura"


def test_convert_media_no_produces_verified_expert():
    df = _master_df(_master_row(
        confianza="MEDIA",
        sector_serio="Cría y explotación de animales",
        justificacion="Extensión funcional razonable, agregación defendible.",
    ))
    out = convert_master_to_authoring(df, _NAME_TO_CODE)
    row = out.iloc[0]
    assert row["status"] == AuthoringStatus.VERIFIED.value
    assert row["evidence_type"] == EvidenceType.EXPERT.value
    assert row["serio_sector"] == "112"


def test_convert_media_si_produces_review_required_with_empty_sector():
    df = _master_df(_master_row(
        confianza="MEDIA", requiere_revision="SI",
        sector_serio="Industria alimentaria",  # candidato, no destino final
        justificacion="Renumeración de catálogo; requiere confirmación.",
    ))
    out = convert_master_to_authoring(df, _NAME_TO_CODE)
    row = out.iloc[0]
    assert row["status"] == AuthoringStatus.REVIEW_REQUIRED.value
    assert row["mapping_type"] == MappingType.PARTIAL.value
    assert row["serio_sector"] == ""       # invariante: REVIEW_REQUIRED exige vacío
    assert row["serio_nombre"] == ""
    assert "Industria alimentaria" in row["notes"]   # el candidato se conserva en notes


def test_convert_baja_si_produces_review_required_ambiguous_without_candidate():
    df = _master_df(_master_row(
        nivel_scian="sector", codigo_scian="11", descripcion_scian="Sector agropecuario",
        confianza="BAJA", requiere_revision="SI", sector_serio="",
        justificacion="Agrupa varios subsectores heterogéneos.",
    ))
    out = convert_master_to_authoring(df, _NAME_TO_CODE)
    row = out.iloc[0]
    assert row["status"] == AuthoringStatus.REVIEW_REQUIRED.value
    assert row["mapping_type"] == MappingType.AMBIGUOUS.value
    assert row["serio_sector"] == ""


def test_convert_unsupported_confianza_revision_combo_raises():
    df = _master_df(_master_row(confianza="ALTA", requiere_revision="SI"))
    with pytest.raises(CrosswalkMaestroError):
        convert_master_to_authoring(df, _NAME_TO_CODE)


def test_convert_verified_row_without_sector_name_raises():
    df = _master_df(_master_row(sector_serio=""))
    with pytest.raises(CrosswalkMaestroError):
        convert_master_to_authoring(df, _NAME_TO_CODE)


def test_convert_unknown_serio_name_raises():
    df = _master_df(_master_row(sector_serio="Sector Que No Existe En El Catálogo"))
    with pytest.raises(CrosswalkMaestroError):
        convert_master_to_authoring(df, _NAME_TO_CODE)


def test_convert_unknown_nivel_scian_raises():
    df = _master_df(_master_row(nivel_scian="division"))
    with pytest.raises(CrosswalkMaestroError):
        convert_master_to_authoring(df, _NAME_TO_CODE)


# ════════════════════════════════════════════════════════════════════════
# Migración completa a disco + validate_authoring() sobre el resultado
# ════════════════════════════════════════════════════════════════════════
def test_build_authoring_csv_from_master_writes_valid_authoring_schema(tmp_path):
    master_path = tmp_path / "maestro.csv"
    _master_df(
        _master_row(),
        _master_row(codigo_scian="112", sector_serio="Cría y explotación de animales"),
        _master_row(
            nivel_scian="sector", codigo_scian="11", descripcion_scian="Sector agropecuario",
            confianza="BAJA", requiere_revision="SI", sector_serio="",
            justificacion="Heterogéneo, requiere resolución en subsector.",
        ),
    ).to_csv(master_path, index=False)

    sectores_path = tmp_path / "sectores.csv"
    pd.DataFrame({"scian": _SERIO_CODES, "nombre": list(_NAME_TO_CODE.keys())}).to_csv(sectores_path, index=False)

    out_path = tmp_path / "crosswalk_autoria.csv"
    build_authoring_csv_from_master(
        master_path, sectores_path, out_path,
        crosswalk_version="v0.1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )

    builder = CrosswalkBuilder(serio_sectors=_SERIO_CODES)
    authoring_df = builder.load_authoring(out_path)
    assert list(authoring_df.columns) == AUTHORING_SCHEMA
    assert len(authoring_df) == 3

    validated, report = builder.validate_authoring(authoring_df)
    assert report.n_invalid == 0
    assert report.n_valid == 3


def test_real_v0_1_master_file_migrates_and_validates_cleanly(tmp_path):
    """
    Prueba de regresión sobre el activo real entregado por el equipo de
    autoría (Crosswalk_Maestro_SCIAN_SERIO_v0.1.csv, 422 filas): debe
    migrar y pasar validate_authoring() sin ninguna violación. Esta es la
    garantía de que el archivo que de verdad se commitea al repositorio
    es compatible con el pipeline, no solo un ejemplo sintético.
    """
    serio_codes, _ = load_serio_catalog(SERIO_SECTORES_CSV)
    out_path = tmp_path / "crosswalk_autoria_real.csv"

    build_authoring_csv_from_master(
        CROSSWALK_MASTER_RAW_CSV, SERIO_SECTORES_CSV, out_path,
        crosswalk_version="v0.1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )

    builder = CrosswalkBuilder(serio_sectors=serio_codes)
    authoring_df = builder.load_authoring(out_path)
    assert len(authoring_df) == 422

    validated, report = builder.validate_authoring(authoring_df)
    assert report.n_invalid == 0
    assert report.n_total == 422


# ════════════════════════════════════════════════════════════════════════
# compile_to_flat_lookup() + save_compiled_lookup() + compatibilidad con
# el contrato EXISTENTE (validate / build_lookup / apply), sin modificarlo
# ════════════════════════════════════════════════════════════════════════
@pytest.fixture
def compiled_pipeline(tmp_path):
    """Migra un Crosswalk Maestro sintético de 2 filas VERIFIED (subsector,
    con herencia hacia Clase) y devuelve (builder, authoring_df validado)."""
    master_path = tmp_path / "maestro.csv"
    _master_df(
        _master_row(),  # subsector 111 → sector SERIO 111, VERIFIED
        _master_row(
            nivel_scian="subsector", codigo_scian="311",
            descripcion_scian="Industria alimentaria",
            sector_serio="Industria alimentaria", confianza="ALTA", requiere_revision="NO",
            justificacion="Coincidencia directa con el sector SERIO 311.",
        ),
    ).to_csv(master_path, index=False)

    sectores_path = tmp_path / "sectores.csv"
    pd.DataFrame({"scian": _SERIO_CODES, "nombre": list(_NAME_TO_CODE.keys())}).to_csv(sectores_path, index=False)

    authoring_path = tmp_path / "crosswalk_autoria.csv"
    build_authoring_csv_from_master(
        master_path, sectores_path, authoring_path,
        crosswalk_version="v0.1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )

    builder = CrosswalkBuilder(serio_sectors=_SERIO_CODES)
    authoring_df = builder.load_authoring(authoring_path)
    authoring_df, report = builder.validate_authoring(authoring_df)
    assert report.n_invalid == 0
    return builder, authoring_df


def test_compile_to_flat_lookup_resolves_via_subsector_inheritance(compiled_pipeline):
    builder, authoring_df = compiled_pipeline
    compiled = builder.compile_to_flat_lookup(
        authoring_df, observed_scian_codes=["111111", "311611", "999999"]
    )
    assert list(compiled.columns) == CROSSWALK_SCHEMA
    assert set(compiled["scian_codigo"]) == {"111111", "311611"}  # 999999 sin regla
    lookup = dict(zip(compiled["scian_codigo"], compiled["sector_serio"]))
    assert lookup["111111"] == "111"
    assert lookup["311611"] == "311"


def test_save_compiled_lookup_writes_expected_csv(tmp_path, compiled_pipeline):
    builder, authoring_df = compiled_pipeline
    compiled = builder.compile_to_flat_lookup(authoring_df, observed_scian_codes=["111111"])

    out_path = tmp_path / "crosswalk_scian_serio.csv"
    returned_path = builder.save_compiled_lookup(compiled, out_path)

    assert returned_path == out_path
    assert out_path.exists()
    reloaded = pd.read_csv(out_path, dtype=str)
    assert list(reloaded.columns) == CROSSWALK_SCHEMA
    assert reloaded.loc[0, "scian_codigo"] == "111111"
    assert reloaded.loc[0, "sector_serio"] == "111"


def test_save_compiled_lookup_rejects_wrong_schema(tmp_path, compiled_pipeline):
    builder, _ = compiled_pipeline
    bad_df = pd.DataFrame({"a": [1], "b": [2]})
    with pytest.raises(ValueError):
        builder.save_compiled_lookup(bad_df, tmp_path / "salida.csv")


def test_compiled_lookup_feeds_existing_public_contract_unchanged(tmp_path, compiled_pipeline):
    """Integración de extremo a extremo hasta el contrato EXISTENTE que ya
    consume WarehouseBuilder — sin modificar validate()/build_lookup()/apply()."""
    builder, authoring_df = compiled_pipeline
    compiled = builder.compile_to_flat_lookup(authoring_df, observed_scian_codes=["111111", "311611"])
    compiled_path = builder.save_compiled_lookup(compiled, tmp_path / "crosswalk_scian_serio.csv")

    # A partir de aquí, exactamente el mismo camino que WarehouseBuilder.apply_crosswalk():
    cw_df = builder.load(compiled_path)              # método EXISTENTE, sin cambios
    validated, cw_report = builder.validate(cw_df)    # método EXISTENTE, sin cambios
    assert cw_report.n_invalid == 0
    lookup = builder.build_lookup(validated)          # método EXISTENTE, sin cambios
    assert lookup == {"111111": "111", "311611": "311"}

    denue = pd.DataFrame({"id": ["A1", "A2", "A3"], "scian": ["111111", "311611", "000000"]})
    mapped, unmapped = builder.apply(denue, lookup, scian_col="scian")  # método EXISTENTE
    assert mapped.loc[0, "sector_serio"] == "111"
    assert mapped.loc[1, "sector_serio"] == "311"
    assert unmapped == ["000000"]
