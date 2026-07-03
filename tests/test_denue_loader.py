# tests/test_denue_loader.py
"""
Pruebas de DENUELoader con un CSV sintético que imita el esquema real del
DENUE (INEGI), incluyendo casos con coordenadas nulas/fuera de rango y
rangos de personal ocupado no reconocidos.
"""
import pandas as pd
import pytest

from spatial.warehouse.denue_loader import DENUELoader, PER_OCU_MIDPOINT


def _make_denue_df() -> pd.DataFrame:
    return pd.DataFrame({
        "id": ["A1", "A2", "A3", "A4", "A5"],
        "nom_estab": ["Tienda 1", "Taller 2", "Restaurante 3", "Farmacia 4", "Oficina 5"],
        "codigo_act": ["461110", "811192", "722511", "464111", ""],
        "latitud":  [20.5888, 19.4326, 25.6866, None, 40.0],   # A4 nula, A5 fuera de rango MX
        "longitud": [-100.3899, -99.1332, -100.3161, -103.3496, -100.0],
        "per_ocu": [
            "0 a 5 personas", "6 a 10 personas", "251 y más personas",
            "11 a 30 personas", "rango_desconocido",
        ],
    })


@pytest.fixture
def loader():
    return DENUELoader()


@pytest.fixture
def raw_df():
    return _make_denue_df()


def test_validate_flags_null_and_out_of_range_coords(loader, raw_df):
    validated, report = loader.validate(raw_df)
    assert report.n_total == 5
    assert len(validated) == 5  # sin descarte
    assert report.checks["chk_lat_not_null"] == 1     # A4
    assert report.checks["chk_lat_in_range"] >= 2      # A4 (nula) + A5 (lat 40)
    assert report.n_invalid >= 2


def test_validate_flags_missing_scian(loader, raw_df):
    _, report = loader.validate(raw_df)
    assert report.checks["chk_scian_present"] == 1  # A5 con codigo_act vacío


def test_filter_valid_drops_only_flagged(loader, raw_df):
    validated, _ = loader.validate(raw_df)
    filtered = loader.filter_valid(validated)
    assert len(filtered) == 3  # A1, A2, A3 son válidos; A4 y A5 no
    assert set(filtered["id"]) == {"A1", "A2", "A3"}


def test_normalize_builds_point_geometry_and_employment(loader, raw_df):
    normalized = loader.normalize(raw_df)
    assert "geometry" in normalized.columns
    assert normalized.crs.to_epsg() == loader.epsg_target
    assert normalized.loc[0, "empleo_estimado"] == PER_OCU_MIDPOINT["0 a 5 personas"]
    # rango desconocido → NaN explícito, no inventado
    assert pd.isna(normalized.loc[4, "empleo_estimado"])


def test_normalize_raises_without_lat_lon(loader):
    df = pd.DataFrame({"id": ["A1"], "codigo_act": ["461110"]})
    with pytest.raises(ValueError):
        loader.normalize(df)


def test_full_pipeline_run(tmp_path, loader, raw_df):
    src = tmp_path / "denue_test.csv"
    raw_df.to_csv(src, index=False, encoding="utf-8")
    result = loader.run(src, drop_invalid=True)
    assert len(result["normalized"]) == 3
    assert result["report"].n_valid == 3
