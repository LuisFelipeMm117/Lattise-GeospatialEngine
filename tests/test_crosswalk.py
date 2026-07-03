# tests/test_crosswalk.py
"""
Pruebas de CrosswalkBuilder: generación de plantilla, validación de
biunivocidad (sin resolución automática de excepciones) y aplicación
sobre un DENUE normalizado sintético.
"""
import pandas as pd
import pytest

from spatial.warehouse.crosswalk import CrosswalkBuilder, CROSSWALK_SCHEMA

SERIO_SECTORS = [f"SEC{i:03d}" for i in range(1, 6)]  # universo reducido para pruebas


@pytest.fixture
def cb():
    return CrosswalkBuilder(serio_sectors=SERIO_SECTORS)


def _valid_table() -> pd.DataFrame:
    return pd.DataFrame({
        "scian_codigo": ["461110", "811192", "722511"],
        "sector_serio": ["SEC001", "SEC002", "SEC003"],
        "notas": ["", "", ""],
    })


def test_generate_template_has_correct_schema(tmp_path, cb):
    out = cb.generate_template(tmp_path / "crosswalk.csv")
    df = pd.read_csv(out)
    assert list(df.columns) == CROSSWALK_SCHEMA
    assert len(df) == 0

    ref = tmp_path / "crosswalk_sectores_serio_referencia.csv"
    assert ref.exists()
    ref_df = pd.read_csv(ref)
    assert set(ref_df["sector_serio"]) == set(SERIO_SECTORS)


def test_validate_passes_on_clean_table(cb):
    df, report = cb.validate(_valid_table())
    assert report.n_valid == 3
    assert report.n_invalid == 0
    assert report.duplicated_codes == []
    assert report.codes_outside_universe == []


def test_validate_flags_duplicate_scian_without_resolving(cb):
    df = _valid_table()
    df.loc[3] = ["461110", "SEC004", "mapeo alternativo"]  # mismo scian, otro sector
    validated, report = cb.validate(df)

    assert "461110" in report.duplicated_codes
    # Ambas filas del código duplicado quedan marcadas como inválidas —
    # ninguna se "gana" automáticamente.
    dup_rows = validated[validated["scian_codigo"] == "461110"]
    assert not dup_rows["_valid_mapping"].any()


def test_validate_flags_sector_outside_universe(cb):
    df = _valid_table()
    df.loc[3] = ["999999", "SECTOR_INEXISTENTE", ""]
    _, report = cb.validate(df)
    assert "SECTOR_INEXISTENTE" in report.codes_outside_universe


def test_validate_flags_bad_scian_format(cb):
    df = _valid_table()
    df.loc[3] = ["ABC123", "SEC004", ""]  # no son 6 dígitos numéricos
    validated, report = cb.validate(df)
    assert report.checks["chk_scian_format"] >= 1


def test_build_lookup_excludes_invalid_and_duplicates(cb):
    df = _valid_table()
    df.loc[3] = ["461110", "SEC004", "duplicado"]  # duplica el primero
    validated, _ = cb.validate(df)
    lookup = cb.build_lookup(validated)
    assert "461110" not in lookup            # excluido por ambigüedad
    assert lookup["811192"] == "SEC002"      # el resto sigue disponible


def test_apply_maps_known_codes_and_reports_unmapped(cb):
    validated, _ = cb.validate(_valid_table())
    lookup = cb.build_lookup(validated)

    denue = pd.DataFrame({"id": ["A1", "A2", "A3"], "scian": ["461110", "811192", "000000"]})
    mapped, unmapped = cb.apply(denue, lookup, scian_col="scian")

    assert mapped.loc[0, "sector_serio"] == "SEC001"
    assert mapped.loc[1, "sector_serio"] == "SEC002"
    assert pd.isna(mapped.loc[2, "sector_serio"])
    assert unmapped == ["000000"]
    assert len(mapped) == 3  # ninguna fila del DENUE se descarta
