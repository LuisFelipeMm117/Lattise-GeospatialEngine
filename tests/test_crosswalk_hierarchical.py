# tests/test_crosswalk_hierarchical.py
"""
Pruebas de la capa de AUTORÍA JERÁRQUICA de CrosswalkBuilder:

    Autoría jerárquica → Validación → Compilación → Lookup plano → WarehouseBuilder

Cubre:
  - AUTHORING_SCHEMA / generate_authoring_template / load_authoring
  - validate_authoring (5 categorías de error + detector de asignación múltiple)
  - resolve_scian_code (algoritmo de resolución jerárquica y su precedencia)
  - suggest_inferred_rows (regla dura: INFERRED nunca produce VERIFIED)
  - compile_to_flat_lookup (puente hacia CROSSWALK_SCHEMA, el contrato existente)
  - build_coverage_report / CrosswalkCoverageReport (dos métricas de cobertura,
    priority_breakdown, review_queue, versionamiento)

Esta suite es completamente independiente de tests/test_crosswalk.py: no
modifica, reutiliza ni depende de sus fixtures, para garantizar que la
suite original permanezca intacta y siga pasando sin cambios.
"""
import json

import pandas as pd
import pytest

from spatial.warehouse.crosswalk import (
    CrosswalkBuilder,
    CROSSWALK_SCHEMA,
    AUTHORING_SCHEMA,
    SCIANLevel,
    EvidenceType,
    AuthoringStatus,
    MappingType,
    Priority,
    ScianResolution,
    AuthoringValidationReport,
    CrosswalkCoverageReport,
    DuplicateSCIANError,
    UnknownSERIOSectorError,
    InvalidSCIANLengthError,
    NonNumericSCIANError,
    StateConsistencyError,
    scian_ancestors,
    RESOLUTION_ORDER,
)

SERIO_SECTORS = [f"SEC{i:03d}" for i in range(1, 6)]  # universo reducido, igual que test_crosswalk.py


@pytest.fixture
def cb():
    return CrosswalkBuilder(serio_sectors=SERIO_SECTORS)


def _row(**overrides) -> dict:
    """Fila de autoría VERIFIED válida por defecto — los tests solo
    sobrescriben lo que necesitan para forzar el escenario bajo prueba."""
    base = {
        "scian_codigo": "311611",
        "scian_nivel": SCIANLevel.CLASE.value,
        "scian_titulo": "Elaboración de alimento balanceado",
        "serio_sector": "SEC001",
        "serio_nombre": "Sector Uno",
        "evidence_type": EvidenceType.OFFICIAL.value,
        "status": AuthoringStatus.VERIFIED.value,
        "priority": Priority.HIGH.value,
        "mapping_type": MappingType.EXACT.value,
        "source": "Catálogo oficial INEGI-SERIO",
        "justification": "Correspondencia 1:1 documentada",
        "reviewed_by": "tester",
        "review_date": "2026-07-04",
        "notes": "",
        "crosswalk_version": "v-test-1",
        "scian_version": "SCIAN-2018",
        "serio_version": "SERIO-78-2018",
        "generated_at": "2026-07-04T00:00:00+00:00",
        "generated_by": "test-suite",
    }
    base.update(overrides)
    return base


def _authoring_df(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=AUTHORING_SCHEMA)


# ════════════════════════════════════════════════════════════════════════
# ETAPA 0/1 — Jerarquía y esquema de autoría
# ════════════════════════════════════════════════════════════════════════
def test_scian_ancestors_computes_all_five_prefixes():
    ancestors = scian_ancestors("311611")
    assert ancestors[SCIANLevel.CLASE] == "311611"
    assert ancestors[SCIANLevel.SUBRAMA] == "31161"
    assert ancestors[SCIANLevel.RAMA] == "3116"
    assert ancestors[SCIANLevel.SUBSECTOR] == "311"
    assert ancestors[SCIANLevel.SECTOR] == "31"


def test_scian_ancestors_rejects_non_class_code():
    with pytest.raises(ValueError):
        scian_ancestors("31")  # no es un código de Clase de 6 dígitos


def test_resolution_order_is_most_specific_first():
    assert RESOLUTION_ORDER == (
        SCIANLevel.CLASE, SCIANLevel.SUBRAMA, SCIANLevel.RAMA,
        SCIANLevel.SUBSECTOR, SCIANLevel.SECTOR,
    )


def test_generate_authoring_template_has_correct_schema(tmp_path, cb):
    out = cb.generate_authoring_template(
        tmp_path / "crosswalk_autoria.csv",
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    df = pd.read_csv(out)
    assert list(df.columns) == AUTHORING_SCHEMA
    assert len(df) == 0


def test_generate_authoring_template_injects_version_metadata_only_when_missing(tmp_path, cb):
    rows = [
        _row(scian_codigo="311611", crosswalk_version=""),           # sin versión → se rellena
        _row(scian_codigo="722511", crosswalk_version="v-manual"),   # ya tiene versión → se respeta
    ]
    out = cb.generate_authoring_template(
        tmp_path / "crosswalk_autoria.csv",
        crosswalk_version="v-auto", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
        rows=rows,
    )
    df = pd.read_csv(out, dtype=str)
    got = dict(zip(df["scian_codigo"], df["crosswalk_version"]))
    assert got["311611"] == "v-auto"
    assert got["722511"] == "v-manual"


def test_load_authoring_roundtrip(tmp_path, cb):
    rows = [_row(scian_codigo="311611"), _row(scian_codigo="722511", serio_sector="SEC002")]
    path = cb.generate_authoring_template(
        tmp_path / "crosswalk_autoria.csv",
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
        rows=rows,
    )
    loaded = cb.load_authoring(path)
    assert list(loaded.columns) == AUTHORING_SCHEMA
    assert set(loaded["scian_codigo"]) == {"311611", "722511"}


def test_load_authoring_missing_file_raises(tmp_path, cb):
    with pytest.raises(FileNotFoundError):
        cb.load_authoring(tmp_path / "no_existe.csv")


# ════════════════════════════════════════════════════════════════════════
# ETAPA 2 — Validación de autoría (5 categorías + detector informativo)
# ════════════════════════════════════════════════════════════════════════
def test_validate_authoring_passes_clean_table(cb):
    df = _authoring_df(
        _row(scian_codigo="311611", serio_sector="SEC001"),
        _row(
            scian_codigo="72", scian_nivel=SCIANLevel.SECTOR.value,
            scian_titulo="Sector servicios de alojamiento", serio_sector="SEC002",
        ),
    )
    validated, report = cb.validate_authoring(df)
    assert isinstance(report, AuthoringValidationReport)
    assert report.n_invalid == 0
    assert report.n_valid == 2


def test_validate_authoring_duplicate_scian_raises(cb):
    df = _authoring_df(
        _row(scian_codigo="311611"),
        _row(scian_codigo="311611", serio_sector="SEC002"),
    )
    with pytest.raises(DuplicateSCIANError):
        cb.validate_authoring(df)


def test_validate_authoring_unknown_sector_raises(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SECTOR_INEXISTENTE"))
    with pytest.raises(UnknownSERIOSectorError):
        cb.validate_authoring(df)


def test_validate_authoring_invalid_length_raises(cb):
    # scian_nivel=CLASE exige 6 dígitos; se entregan 5.
    df = _authoring_df(_row(scian_codigo="31161", scian_nivel=SCIANLevel.CLASE.value))
    with pytest.raises(InvalidSCIANLengthError):
        cb.validate_authoring(df)


def test_validate_authoring_unknown_level_raises_invalid_length(cb):
    df = _authoring_df(_row(scian_codigo="311611", scian_nivel="NIVEL_INEXISTENTE"))
    with pytest.raises(InvalidSCIANLengthError):
        cb.validate_authoring(df)


def test_validate_authoring_non_numeric_raises(cb):
    df = _authoring_df(_row(scian_codigo="3A1611"))
    with pytest.raises(NonNumericSCIANError):
        cb.validate_authoring(df)


def test_validate_authoring_verified_without_sector_raises_state_error(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector=""))
    with pytest.raises(StateConsistencyError):
        cb.validate_authoring(df)


def test_validate_authoring_pending_with_sector_raises_state_error(cb):
    df = _authoring_df(_row(
        scian_codigo="311611", status=AuthoringStatus.PENDING.value,
        serio_sector="SEC001",  # PENDING debe tener serio_sector vacío
    ))
    with pytest.raises(StateConsistencyError):
        cb.validate_authoring(df)


def test_validate_authoring_verified_cannot_have_inferred_evidence(cb):
    df = _authoring_df(_row(scian_codigo="311611", evidence_type=EvidenceType.INFERRED.value))
    with pytest.raises(StateConsistencyError):
        cb.validate_authoring(df)


def test_validate_authoring_review_required_valid_shape(cb):
    df = _authoring_df(_row(
        scian_codigo="311611", status=AuthoringStatus.REVIEW_REQUIRED.value,
        serio_sector="", mapping_type=MappingType.AMBIGUOUS.value,
        evidence_type=EvidenceType.EXPERT.value, justification="",
    ))
    _, report = cb.validate_authoring(df)
    assert report.n_invalid == 0


def test_validate_authoring_strict_false_returns_report_without_raising(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SECTOR_INEXISTENTE"))
    validated, report = cb.validate_authoring(df, strict=False)
    assert report.n_invalid == 1
    assert "SECTOR_INEXISTENTE" in report.violations["unknown_serio_sector"]


def test_validate_authoring_reports_all_categories_in_exception_message(cb):
    df = _authoring_df(
        _row(scian_codigo="3A1611", scian_titulo="dup"),           # no numérico
        _row(scian_codigo="311612", serio_sector="SECTOR_FALSO"),  # sector desconocido
    )
    with pytest.raises((NonNumericSCIANError, UnknownSERIOSectorError)) as exc_info:
        cb.validate_authoring(df)
    msg = str(exc_info.value)
    assert "non_numeric_scian" in msg
    assert "unknown_serio_sector" in msg


def test_validate_authoring_detects_multiple_semantic_assignment_without_raising(cb):
    df = _authoring_df(
        _row(scian_codigo="311611", scian_titulo="Comercio al por mayor de X", serio_sector="SEC001"),
        _row(scian_codigo="311612", scian_titulo="comercio al por mayor de x", serio_sector="SEC002"),
    )
    _, report = cb.validate_authoring(df, strict=False)
    assert "comercio al por mayor de x" in report.multiple_semantic_assignments


# ════════════════════════════════════════════════════════════════════════
# ETAPA 3 — Motor de resolución jerárquica
# ════════════════════════════════════════════════════════════════════════
def test_resolve_scian_code_exact_class_match(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    res = cb.resolve_scian_code("311611", df)
    assert res.resolved is True
    assert res.serio_sector == "SEC001"
    assert res.matched_level == SCIANLevel.CLASE
    assert res.matched_scian_codigo == "311611"


def test_resolve_scian_code_falls_back_to_subsector(cb):
    # No hay regla en Clase/Subrama/Rama; solo existe la regla de Subsector "311".
    df = _authoring_df(_row(
        scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
        scian_titulo="Industria alimentaria", serio_sector="SEC003",
    ))
    res = cb.resolve_scian_code("311611", df)
    assert res.resolved is True
    assert res.serio_sector == "SEC003"
    assert res.matched_level == SCIANLevel.SUBSECTOR
    assert res.matched_scian_codigo == "311"


def test_resolve_scian_code_class_rule_takes_precedence_over_subsector(cb):
    df = _authoring_df(
        _row(scian_codigo="311611", serio_sector="SEC001"),  # más específica
        _row(
            scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
            scian_titulo="Industria alimentaria", serio_sector="SEC003",
        ),
    )
    res = cb.resolve_scian_code("311611", df)
    assert res.serio_sector == "SEC001"          # gana Clase, no Subsector
    assert res.matched_level == SCIANLevel.CLASE


def test_resolve_scian_code_subrama_takes_precedence_over_rama_and_sector(cb):
    df = _authoring_df(
        _row(
            scian_codigo="31161", scian_nivel=SCIANLevel.SUBRAMA.value,
            scian_titulo="Subrama X", serio_sector="SEC002",
        ),
        _row(
            scian_codigo="3116", scian_nivel=SCIANLevel.RAMA.value,
            scian_titulo="Rama X", serio_sector="SEC003",
        ),
        _row(
            scian_codigo="31", scian_nivel=SCIANLevel.SECTOR.value,
            scian_titulo="Sector X", serio_sector="SEC004",
        ),
    )
    res = cb.resolve_scian_code("311611", df)
    assert res.serio_sector == "SEC002"
    assert res.matched_level == SCIANLevel.SUBRAMA


def test_resolve_scian_code_unresolved_when_no_rule_anywhere(cb):
    df = _authoring_df(_row(scian_codigo="722511", serio_sector="SEC001"))  # otra rama, sin relación
    res = cb.resolve_scian_code("311611", df)
    assert res.resolved is False
    assert res.serio_sector is None


def test_resolve_scian_code_ignores_non_verified_rows(cb):
    # Regla a nivel Clase pero PENDING (sin sector) → no debe resolver ahí;
    # cae al Subsector, que sí está VERIFIED.
    df = _authoring_df(
        _row(scian_codigo="311611", status=AuthoringStatus.PENDING.value, serio_sector="", evidence_type=""),
        _row(
            scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
            scian_titulo="Industria alimentaria", serio_sector="SEC003",
        ),
    )
    res = cb.resolve_scian_code("311611", df)
    assert res.resolved is True
    assert res.matched_level == SCIANLevel.SUBSECTOR
    assert res.serio_sector == "SEC003"


def test_resolve_scian_code_rejects_non_class_input(cb):
    df = _authoring_df(_row(scian_codigo="311611"))
    with pytest.raises(ValueError):
        cb.resolve_scian_code("31", df)  # no es un código de Clase de 6 dígitos


def test_resolve_scian_code_raises_on_duplicate_verified_rule(cb):
    # Simula una tabla corrupta (dos reglas VERIFIED para el mismo nivel+código)
    # que validate_authoring ya debería haber rechazado — resolve_scian_code
    # debe fallar duro en vez de elegir una arbitrariamente.
    df = _authoring_df(
        _row(scian_codigo="31", scian_nivel=SCIANLevel.SECTOR.value,
             scian_titulo="Sector X", serio_sector="SEC001"),
        _row(scian_codigo="31", scian_nivel=SCIANLevel.SECTOR.value,
             scian_titulo="Sector X duplicado", serio_sector="SEC002"),
    )
    with pytest.raises(StateConsistencyError):
        cb.resolve_scian_code("311611", df)


# ════════════════════════════════════════════════════════════════════════
# suggest_inferred_rows — regla dura: INFERRED nunca produce VERIFIED
# ════════════════════════════════════════════════════════════════════════
def test_suggest_inferred_rows_proposes_pending_from_ancestor(cb):
    df = _authoring_df(_row(
        scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
        scian_titulo="Industria alimentaria", serio_sector="SEC003",
    ))
    suggestions = cb.suggest_inferred_rows(
        df, observed_scian_codes=["311611"],
        crosswalk_version="v1", scian_version="SCIAN-2018",
    )
    assert len(suggestions) == 1
    row = suggestions.iloc[0]
    assert row["status"] == AuthoringStatus.PENDING.value
    assert row["evidence_type"] == EvidenceType.INFERRED.value
    assert row["serio_sector"] == ""              # NUNCA se rellena automáticamente
    assert "SEC003" in row["notes"]               # el candidato se documenta en notas


def test_suggest_inferred_rows_skips_codes_with_existing_class_row(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    suggestions = cb.suggest_inferred_rows(df, observed_scian_codes=["311611"])
    assert suggestions.empty


def test_suggest_inferred_rows_marks_empty_evidence_when_no_ancestor_rule(cb):
    df = _authoring_df(_row(scian_codigo="722511", serio_sector="SEC001"))  # sin relación jerárquica
    suggestions = cb.suggest_inferred_rows(df, observed_scian_codes=["311611"])
    row = suggestions.iloc[0]
    assert row["evidence_type"] == ""
    assert row["status"] == AuthoringStatus.PENDING.value
    assert row["serio_sector"] == ""


def test_suggest_inferred_rows_never_returns_verified_status(cb):
    df = _authoring_df(_row(
        scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
        scian_titulo="Industria alimentaria", serio_sector="SEC003",
    ))
    suggestions = cb.suggest_inferred_rows(df, observed_scian_codes=["311611", "311612", "311699"])
    assert (suggestions["status"] == AuthoringStatus.PENDING.value).all()
    assert not (suggestions["status"] == AuthoringStatus.VERIFIED.value).any()


# ════════════════════════════════════════════════════════════════════════
# ETAPA 4 — Compilador a artefacto plano (CROSSWALK_SCHEMA)
# ════════════════════════════════════════════════════════════════════════
def test_compile_to_flat_lookup_produces_exact_crosswalk_schema(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    compiled = cb.compile_to_flat_lookup(df, observed_scian_codes=["311611"])
    assert list(compiled.columns) == CROSSWALK_SCHEMA


def test_compile_to_flat_lookup_resolves_via_hierarchy(cb):
    df = _authoring_df(_row(
        scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
        scian_titulo="Industria alimentaria", serio_sector="SEC003",
    ))
    compiled = cb.compile_to_flat_lookup(df, observed_scian_codes=["311611", "311612"])
    assert set(compiled["scian_codigo"]) == {"311611", "311612"}
    assert (compiled["sector_serio"] == "SEC003").all()


def test_compile_to_flat_lookup_excludes_unresolved_codes(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    compiled = cb.compile_to_flat_lookup(df, observed_scian_codes=["311611", "999999", "ABCDEF"])
    assert set(compiled["scian_codigo"]) == {"311611"}  # 999999 sin regla, ABCDEF formato inválido


def test_compile_to_flat_lookup_feeds_existing_public_contract_unchanged(cb):
    """Prueba de integración: el artefacto compilado debe fluir sin cambios
    por validate() → build_lookup() → apply(), el contrato público
    EXISTENTE que WarehouseBuilder ya consume, sin ninguna modificación."""
    authoring_df = _authoring_df(
        _row(scian_codigo="311611", serio_sector="SEC001"),
        _row(
            scian_codigo="722", scian_nivel=SCIANLevel.SUBSECTOR.value,
            scian_titulo="Servicios de preparación de alimentos", serio_sector="SEC002",
        ),
    )
    compiled = cb.compile_to_flat_lookup(authoring_df, observed_scian_codes=["311611", "722511"])

    validated, cw_report = cb.validate(compiled)     # método EXISTENTE, sin cambios
    assert cw_report.n_invalid == 0
    lookup = cb.build_lookup(validated)              # método EXISTENTE, sin cambios
    assert lookup == {"311611": "SEC001", "722511": "SEC002"}

    denue = pd.DataFrame({"id": ["A1", "A2", "A3"], "scian": ["311611", "722511", "000000"]})
    mapped, unmapped = cb.apply(denue, lookup, scian_col="scian")  # método EXISTENTE, sin cambios
    assert mapped.loc[0, "sector_serio"] == "SEC001"
    assert mapped.loc[1, "sector_serio"] == "SEC002"
    assert unmapped == ["000000"]


# ════════════════════════════════════════════════════════════════════════
# ETAPA 5 — CrosswalkCoverageReport / build_coverage_report
# ════════════════════════════════════════════════════════════════════════
def test_build_coverage_report_metadata_and_versioning(cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    report = cb.build_coverage_report(
        df, observed_scian_codes=["311611"], scian_catalog_codes=["311611", "311612"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
        generated_by="pytest",
    )
    assert isinstance(report, CrosswalkCoverageReport)
    assert report.metadata["crosswalk_version"] == "v1"
    assert report.metadata["scian_version"] == "SCIAN-2018"
    assert report.metadata["serio_version"] == "SERIO-78-2018"
    assert report.metadata["generated_by"] == "pytest"
    assert "generated_at" in report.metadata


def test_build_coverage_report_two_coverage_metrics_can_diverge(cb):
    # Catálogo oficial de 4 códigos; solo 1 VERIFIED → coverage_catalog_pct bajo.
    # DENUE observado solo trae ese mismo código → coverage_denue_pct = 100%.
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    report = cb.build_coverage_report(
        df,
        observed_scian_codes=["311611"],
        scian_catalog_codes=["311611", "311612", "311613", "311614"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    assert report.coverage["coverage_denue_pct"] == 100.0
    assert report.coverage["coverage_catalog_pct"] == 25.0
    assert report.coverage["coverage_denue_pct"] != report.coverage["coverage_catalog_pct"]


def test_build_coverage_report_denue_coverage_uses_full_hierarchy(cb):
    # El código observado no tiene fila propia en Clase, pero resuelve por Subsector.
    df = _authoring_df(_row(
        scian_codigo="311", scian_nivel=SCIANLevel.SUBSECTOR.value,
        scian_titulo="Industria alimentaria", serio_sector="SEC003",
    ))
    report = cb.build_coverage_report(
        df, observed_scian_codes=["311611"], scian_catalog_codes=["311611"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    assert report.coverage["coverage_denue_pct"] == 100.0
    assert report.unmapped_scian_codes == []


def test_build_coverage_report_priority_breakdown(cb):
    df = _authoring_df(
        _row(scian_codigo="311611", serio_sector="SEC001", priority=Priority.HIGH.value),
        _row(scian_codigo="311612", serio_sector="SEC001", priority=Priority.HIGH.value,
             status=AuthoringStatus.REVIEW_REQUIRED.value),
    )
    # Ajuste: la segunda fila REVIEW_REQUIRED debe tener serio_sector vacío.
    df.loc[1, "serio_sector"] = ""
    df.loc[1, "mapping_type"] = MappingType.AMBIGUOUS.value
    df.loc[1, "evidence_type"] = EvidenceType.EXPERT.value
    df.loc[1, "justification"] = ""

    report = cb.build_coverage_report(
        df, observed_scian_codes=["311611", "311612"], scian_catalog_codes=["311611", "311612"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    high_bucket = report.priority_breakdown[Priority.HIGH.value]
    assert high_bucket["count"] == 2
    assert high_bucket["verified_pct"] == 50.0


def test_build_coverage_report_review_queue_contains_review_required_rows(cb):
    df = _authoring_df(_row(
        scian_codigo="311611", status=AuthoringStatus.REVIEW_REQUIRED.value,
        serio_sector="", mapping_type=MappingType.AMBIGUOUS.value,
        evidence_type=EvidenceType.EXPERT.value, justification="",
        notes="Podría ser SEC001 o SEC002",
    ))
    report = cb.build_coverage_report(
        df, observed_scian_codes=["311611"], scian_catalog_codes=["311611"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    assert len(report.review_queue) == 1
    assert report.review_queue[0]["scian_codigo"] == "311611"
    assert report.review_queue[0]["notes"] == "Podría ser SEC001 o SEC002"


def test_build_coverage_report_by_serio_sector_and_status_metrics(cb):
    df = _authoring_df(
        _row(scian_codigo="311611", serio_sector="SEC001"),
        _row(scian_codigo="311612", serio_sector="SEC001"),
        _row(scian_codigo="722511", serio_sector="SEC002"),
    )
    report = cb.build_coverage_report(
        df, observed_scian_codes=["311611", "311612", "722511"],
        scian_catalog_codes=["311611", "311612", "722511"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    assert report.coverage["verified_pct"] == 100.0
    sectors = {row["serio_sector"]: row["scian_count"] for row in report.by_serio_sector}
    assert sectors["SEC001"] == 2
    assert sectors["SEC002"] == 1


def test_coverage_report_to_json_is_serializable(tmp_path, cb):
    df = _authoring_df(_row(scian_codigo="311611", serio_sector="SEC001"))
    report = cb.build_coverage_report(
        df, observed_scian_codes=["311611"], scian_catalog_codes=["311611"],
        crosswalk_version="v1", scian_version="SCIAN-2018", serio_version="SERIO-78-2018",
    )
    out = tmp_path / "crosswalk_report.json"
    report.to_json(out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["coverage"]["coverage_catalog_pct"] == 100.0
    assert loaded["metadata"]["crosswalk_version"] == "v1"
