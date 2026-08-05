"""Reporte educativo, reproducible y persistible de una simulación SEE.

Esta capa lee ``ScenarioResult``; no vuelve a correr SERIO, SSD ni SEE. Su
salida JSON está diseñada tanto para una lección/pantalla como para guardar
una simulación del usuario sin perder la procedencia de los datos.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import pandas as pd

from spatial.config import (
    CROSSWALK_COMPILED_CSV,
    CROSSWALK_REPORT_JSON,
    CROSSWALK_VERSION,
    GRAPH_GAL_PATH,
    GRAPH_METADATA_JSON,
    SERIO_DATA_DIR,
    SERIO_VERSION,
    WAREHOUSE_METADATA,
    WAREHOUSE_PARQUET,
)

ENGINE_VERSION = os.environ.get("LATTISE_ENGINE_VERSION", "unversioned")
ENGINE_COMMIT = os.environ.get("LATTISE_GIT_COMMIT")
RHO_METHODS = {"manual", "sensitivity", "morans_i_calibration"}


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, version: Optional[str] = None) -> dict:
    return {
        "path": str(path),
        "available": path.is_file(),
        "version": version or "unversioned",
        "sha256": _sha256(path),
    }


def _json_value(path: Path, key: str, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(key, default)
    except (OSError, json.JSONDecodeError):
        return default


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _educational_warning(rho_method: str) -> str:
    method = {
        "manual": "ρ fue definido manualmente por quien ejecutó el escenario.",
        "sensitivity": "ρ pertenece a un barrido de sensibilidad; compare rangos, no un único valor como certeza.",
        "morans_i_calibration": "ρ fue calibrado por coincidencia de Moran's I, un criterio heurístico de momentos.",
    }[rho_method]
    return (
        f"{method} Este reporte describe una simulación determinista de propagación espacial, "
        "no una estimación causal SAR/SEM/SDM. Los resultados dependen de los supuestos, "
        "de la cobertura espacial y de las versiones de datos registradas aquí."
    )


@dataclass
class EducationalSimulationReport:
    schema_version: str
    report_id: str
    scenario_fingerprint: str
    generated_at_utc: str
    engine: dict
    artifacts: dict
    parameters: dict
    spatial_coverage: dict
    methodological_warning: str
    summary: dict
    ranking: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def summary_text(self) -> str:
        return (
            f"Reporte educativo {self.report_id}: {self.parameters['estado']} · "
            f"sector(es) {', '.join(s['codigo'] for s in self.parameters['sectores'])} · "
            f"{self.spatial_coverage['pct_agebs_con_impacto']:.1f}% de AGEBs con impacto."
        )


def build_educational_report(
    result: Any,
    *,
    rho_method: str = "manual",
    sector_amounts: Optional[Mapping[str, float]] = None,
    warehouse_parquet: str | Path = WAREHOUSE_PARQUET,
    warehouse_metadata: str | Path = WAREHOUSE_METADATA,
    crosswalk_path: str | Path = CROSSWALK_COMPILED_CSV,
    crosswalk_report: str | Path = CROSSWALK_REPORT_JSON,
    graph_gal: str | Path = GRAPH_GAL_PATH,
    graph_metadata: str | Path = GRAPH_METADATA_JSON,
    serio_data_dir: str | Path = SERIO_DATA_DIR,
    bundle_sha256: Optional[str] = None,
    top_n: int = 10,
) -> EducationalSimulationReport:
    """Construye un reporte educativo desde un ``ScenarioResult`` ya calculado.

    ``sector_amounts`` permite representar escenarios compuestos en el futuro;
    si se omite, se registra el único sector y monto de ``Scenario``.
    """
    if rho_method not in RHO_METHODS:
        raise ValueError(f"rho_method debe ser uno de: {', '.join(sorted(RHO_METHODS))}.")
    if top_n < 1:
        raise ValueError("top_n debe ser mayor que cero.")

    report = result.report
    warehouse_parquet = Path(warehouse_parquet)
    warehouse_metadata = Path(warehouse_metadata)
    crosswalk_path = Path(crosswalk_path)
    crosswalk_report = Path(crosswalk_report)
    graph_gal = Path(graph_gal)
    graph_metadata = Path(graph_metadata)
    serio_data_dir = Path(serio_data_dir)

    amounts = sector_amounts or {str(report.sector): float(report.monto_pesos)}
    sectors = [
        {"codigo": str(code), "monto_pesos": float(amount)}
        for code, amount in sorted(amounts.items())
    ]
    bundle_checksum = bundle_sha256 or os.environ.get("LATTISE_ARTIFACT_BUNDLE_SHA256")
    artifacts = {
        "bundle": {
            "sha256": bundle_checksum,
            "status": "configured" if bundle_checksum else "not_configured_local_or_legacy",
        },
        "serio": {
            "data_dir": str(serio_data_dir),
            "version": SERIO_VERSION,
            "meta": _artifact(serio_data_dir / "meta.json", SERIO_VERSION),
        },
        "warehouse": {
            "dataset": _artifact(warehouse_parquet, _json_value(warehouse_metadata, "version")),
            "metadata": _artifact(warehouse_metadata),
        },
        "crosswalk": {
            "dataset": _artifact(crosswalk_path, CROSSWALK_VERSION),
            "report": _artifact(crosswalk_report, CROSSWALK_VERSION),
        },
        "graph": {
            "gal": _artifact(graph_gal, _json_value(graph_metadata, "version")),
            "metadata": _artifact(graph_metadata),
        },
    }

    impacts = pd.DataFrame({
        "cvegeo": result.sm.ids,
        "shock_directo": result.s_series().to_numpy(),
        "impacto_propagado": result.y_series().to_numpy(),
    })
    impacts["impacto_indirecto"] = impacts["impacto_propagado"] - impacts["shock_directo"]
    impacts["impacto_absoluto"] = impacts["impacto_propagado"].abs()
    ranked = impacts.sort_values(["impacto_absoluto", "cvegeo"], ascending=[False, True]).head(top_n)
    ranking = [
        {
            "rango": index + 1,
            "cvegeo": str(row.cvegeo),
            "shock_directo": float(row.shock_directo),
            "impacto_propagado": float(row.impacto_propagado),
            "impacto_indirecto": float(row.impacto_indirecto),
        }
        for index, row in enumerate(ranked.itertuples(index=False))
    ]
    nonzero = impacts["impacto_propagado"].abs() > 1e-12
    direct = impacts["shock_directo"].abs() > 1e-12
    coverage = {
        "n_agebs_matrix": int(len(impacts)),
        "n_agebs_con_shock_directo": int(direct.sum()),
        "n_agebs_con_impacto": int(nonzero.sum()),
        "pct_agebs_con_impacto": float(nonzero.mean() * 100) if len(impacts) else 0.0,
        "n_agebs_desconocidos_en_shock": int(report.n_agebs_desconocidos),
        "sectores_excluidos": list(report.sectores_sin_cobertura_espacial),
        "criterio_contiguidad": report.criterio_contiguidad,
    }
    parameters = {
        "estado": report.estado,
        "estado_key": report.estado_key,
        "sectores": sectors,
        "rho": float(report.rho),
        "metodo_rho": rho_method,
    }
    summary = {
        "shock_inicial_pesos": float(report.monto_pesos),
        "delta_produccion_pesos": float(report.delta_X_total_pesos),
        "delta_valor_agregado_pesos": float(report.delta_VA_total_pesos),
        "delta_empleo": float(report.delta_E_total),
        "suma_shock_directo": float(report.suma_S),
        "suma_impacto_propagado": float(report.suma_Y),
        "multiplicador_espacial_global": report.multiplicador_espacial_global,
    }
    fingerprint_payload = {"artifacts": artifacts, "parameters": parameters, "summary": summary}
    fingerprint = _canonical_sha256(fingerprint_payload)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return EducationalSimulationReport(
        schema_version="1.0",
        report_id=f"edu-{fingerprint[:16]}",
        scenario_fingerprint=fingerprint,
        generated_at_utc=generated_at,
        engine={"version": ENGINE_VERSION, "git_commit": ENGINE_COMMIT},
        artifacts=artifacts,
        parameters=parameters,
        spatial_coverage=coverage,
        methodological_warning=_educational_warning(rho_method),
        summary=summary,
        ranking=ranking,
    )


def build_educational_report_from_engine_result(
    gdf: pd.DataFrame,
    simulation_report: Any,
    scenario: Mapping[str, Any],
    *,
    rho_method: Optional[str] = None,
    bundle_sha256: Optional[str] = None,
    top_n: int = 10,
) -> EducationalSimulationReport:
    """Adapta la salida de ``run_simulation_engine`` para Lattise Studio.

    La interfaz conserva ``(gdf, SimulationReport, scenario)`` en sesión y
    no el ``ScenarioResult`` de Stage 8D. Este adaptador mantiene el mismo
    expediente educativo a partir de esos artefactos ya calculados.
    """
    if top_n < 1:
        raise ValueError("top_n debe ser mayor que cero.")
    resolved_method = rho_method or (
        "morans_i_calibration" if scenario.get("rho_calibrado") else "manual"
    )
    if resolved_method not in RHO_METHODS:
        raise ValueError(f"rho_method debe ser uno de: {', '.join(sorted(RHO_METHODS))}.")

    amounts = scenario.get("shocks") or {
        str(scenario.get("sector", "desconocido")): float(scenario.get("monto_pesos", 0.0))
    }
    sectors = [
        {"codigo": str(code), "monto_pesos": float(amount)}
        for code, amount in sorted(amounts.items())
    ]
    warehouse_path = Path(getattr(simulation_report, "ruta_warehouse_parquet", "") or WAREHOUSE_PARQUET)
    graph_path = Path(getattr(simulation_report, "ruta_graph_gal", "") or GRAPH_GAL_PATH)
    graph_meta_path = Path(getattr(simulation_report, "ruta_graph_metadata", "") or GRAPH_METADATA_JSON)
    bundle_checksum = bundle_sha256 or os.environ.get("LATTISE_ARTIFACT_BUNDLE_SHA256")
    artifacts = {
        "bundle": {
            "sha256": bundle_checksum,
            "status": "configured" if bundle_checksum else "not_configured_local_or_legacy",
        },
        "serio": {
            "data_dir": str(SERIO_DATA_DIR),
            "version": SERIO_VERSION,
            "meta": _artifact(SERIO_DATA_DIR / "meta.json", SERIO_VERSION),
        },
        "warehouse": {
            "dataset": _artifact(warehouse_path, _json_value(WAREHOUSE_METADATA, "version")),
            "metadata": _artifact(WAREHOUSE_METADATA),
        },
        "crosswalk": {
            "dataset": _artifact(CROSSWALK_COMPILED_CSV, CROSSWALK_VERSION),
            "report": _artifact(CROSSWALK_REPORT_JSON, CROSSWALK_VERSION),
        },
        "graph": {
            "gal": _artifact(graph_path, _json_value(graph_meta_path, "version")),
            "metadata": _artifact(graph_meta_path),
        },
    }

    required = {"cvegeo", "shock_directo", "impacto_propagado", "impacto_indirecto"}
    missing = required - set(gdf.columns)
    if missing:
        raise ValueError(f"El resultado del motor no contiene las columnas requeridas: {sorted(missing)}")
    impacts = pd.DataFrame(gdf[["cvegeo", "shock_directo", "impacto_propagado", "impacto_indirecto"]]).copy()
    impacts["impacto_absoluto"] = impacts["impacto_propagado"].abs()
    ranked = impacts.sort_values(["impacto_absoluto", "cvegeo"], ascending=[False, True]).head(top_n)
    ranking = [
        {
            "rango": index + 1,
            "cvegeo": str(row.cvegeo),
            "shock_directo": float(row.shock_directo),
            "impacto_propagado": float(row.impacto_propagado),
            "impacto_indirecto": float(row.impacto_indirecto),
        }
        for index, row in enumerate(ranked.itertuples(index=False))
    ]
    direct = impacts["shock_directo"].abs() > 1e-12
    propagated = impacts["impacto_propagado"].abs() > 1e-12
    excluded = list(getattr(simulation_report, "sectores_sin_cobertura_espacial", []))
    coverage = {
        "n_agebs_matrix": int(len(impacts)),
        "n_agebs_con_shock_directo": int(direct.sum()),
        "n_agebs_con_impacto": int(propagated.sum()),
        "pct_agebs_con_impacto": float(propagated.mean() * 100) if len(impacts) else 0.0,
        "n_agebs_desconocidos_en_shock": len(getattr(simulation_report, "agebs_desconocidos_en_shock", [])),
        "sectores_excluidos": excluded,
        "criterio_contiguidad": getattr(simulation_report, "criterio", None),
    }
    parameters = {
        "estado": scenario.get("estado", "desconocido"),
        "estado_key": scenario.get("estado_key", "desconocido"),
        "sectores": sectors,
        "rho": float(getattr(simulation_report, "rho", scenario.get("rho", 0.0))),
        "metodo_rho": resolved_method,
    }
    summary = {
        "shock_inicial_pesos": float(scenario.get("monto_pesos", 0.0)),
        "delta_produccion_pesos": None,
        "delta_valor_agregado_pesos": None,
        "delta_empleo": None,
        "suma_shock_directo": float(getattr(simulation_report, "shock_total_inicial", 0.0)),
        "suma_impacto_propagado": float(getattr(simulation_report, "shock_total_propagado", 0.0)),
        "multiplicador_espacial_global": getattr(simulation_report, "multiplicador_global", None),
    }
    fingerprint = _canonical_sha256({"artifacts": artifacts, "parameters": parameters, "summary": summary})
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return EducationalSimulationReport(
        schema_version="1.0",
        report_id=f"edu-{fingerprint[:16]}",
        scenario_fingerprint=fingerprint,
        generated_at_utc=generated_at,
        engine={"version": ENGINE_VERSION, "git_commit": ENGINE_COMMIT},
        artifacts=artifacts,
        parameters=parameters,
        spatial_coverage=coverage,
        methodological_warning=_educational_warning(resolved_method),
        summary=summary,
        ranking=ranking,
    )


__all__ = [
    "EducationalSimulationReport", "build_educational_report",
    "build_educational_report_from_engine_result", "RHO_METHODS",
]
