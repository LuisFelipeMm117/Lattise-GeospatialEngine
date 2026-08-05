"""Contrato del adaptador educativo usado por View Results."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from spatial.simulation.educational_report import build_educational_report_from_engine_result


def test_engine_result_adapter_uses_existing_gdf_without_recalculation(tmp_path):
    warehouse = tmp_path / "warehouse.parquet"
    graph = tmp_path / "graph.gal"
    graph_meta = tmp_path / "graph_metadata.json"
    warehouse.write_bytes(b"warehouse")
    graph.write_text("graph", encoding="utf-8")
    graph_meta.write_text('{"criterio": "queen"}', encoding="utf-8")
    engine_report = SimpleNamespace(
        rho=0.42,
        ruta_warehouse_parquet=str(warehouse),
        ruta_graph_gal=str(graph),
        ruta_graph_metadata=str(graph_meta),
        sectores_sin_cobertura_espacial=["999"],
        agebs_desconocidos_en_shock=["missing"],
        criterio="queen",
        shock_total_inicial=100.0,
        shock_total_propagado=140.0,
        multiplicador_global=1.4,
    )
    gdf = pd.DataFrame({
        "cvegeo": ["A", "B", "C"],
        "shock_directo": [100.0, 0.0, 0.0],
        "impacto_propagado": [100.0, 30.0, 10.0],
        "impacto_indirecto": [0.0, 30.0, 10.0],
    })
    scenario = {
        "estado": "Querétaro", "estado_key": "QUERETARO", "monto_pesos": 100.0,
        "shocks": {"111": 100.0}, "rho_calibrado": True,
    }

    report = build_educational_report_from_engine_result(
        gdf, engine_report, scenario, bundle_sha256="b" * 64, top_n=2,
    )

    assert report.parameters["metodo_rho"] == "morans_i_calibration"
    assert report.parameters["rho"] == 0.42
    assert report.spatial_coverage["sectores_excluidos"] == ["999"]
    assert report.spatial_coverage["pct_agebs_con_impacto"] == 100.0
    assert [row["cvegeo"] for row in report.ranking] == ["A", "B"]
    assert report.artifacts["bundle"]["sha256"] == "b" * 64
