#!/usr/bin/env python3
# scripts/build_crosswalk_maestro.py
"""
Orquesta el flujo oficial del Crosswalk Maestro SCIAN → SERIO:

    Crosswalk_Maestro_SCIAN_SERIO_v0.1.csv   (insumo crudo, CROSSWALK_MASTER_RAW_CSV)
      ↓  spatial.warehouse.crosswalk_maestro.build_authoring_csv_from_master()
    crosswalk_autoria_scian_serio.csv        (activo editable, CROSSWALK_AUTHORING_CSV)
      ↓  CrosswalkBuilder.load_authoring()
      ↓  CrosswalkBuilder.validate_authoring()
      ↓  CrosswalkBuilder.compile_to_flat_lookup(observed_scian_codes)   [requiere --denue]
      ↓  CrosswalkBuilder.save_compiled_lookup()
    crosswalk_scian_serio.csv                (artefacto consumido por WarehouseBuilder, CROSSWALK_COMPILED_CSV)

Uso:
    # Solo migrar + validar el activo de autoría (no requiere un DENUE):
    python -m scripts.build_crosswalk_maestro

    # Migrar + validar + compilar contra los códigos SCIAN de un DENUE real:
    python -m scripts.build_crosswalk_maestro --denue data/raw/inegi/denue/denue_22_csv.zip

Este script es intencionalmente un orquestador delgado: toda la lógica de
negocio vive en `spatial.warehouse.crosswalk_maestro` (migración) y
`spatial.warehouse.crosswalk.CrosswalkBuilder` (validación/compilación) —
aquí solo se encadenan las llamadas con las rutas de `spatial.config`.
"""
from __future__ import annotations

import argparse
import sys

from spatial.config import (
    CROSSWALK_AUTHORING_CSV,
    CROSSWALK_COMPILED_CSV,
    CROSSWALK_MASTER_RAW_CSV,
    CROSSWALK_VERSION,
    SCIAN_VERSION,
    SERIO_SECTORES_CSV,
    SERIO_VERSION,
)
from spatial.warehouse.crosswalk import CrosswalkBuilder
from spatial.warehouse.crosswalk_maestro import (
    build_authoring_csv_from_master,
    load_serio_catalog,
)
from spatial.warehouse.denue_loader import DENUELoader


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master", default=CROSSWALK_MASTER_RAW_CSV,
        help="Ruta del Crosswalk Maestro crudo (default: CROSSWALK_MASTER_RAW_CSV).",
    )
    parser.add_argument(
        "--authoring-out", default=CROSSWALK_AUTHORING_CSV,
        help="Ruta de salida del activo de autoría migrado (default: CROSSWALK_AUTHORING_CSV).",
    )
    parser.add_argument(
        "--compiled-out", default=CROSSWALK_COMPILED_CSV,
        help="Ruta de salida del artefacto compilado (default: CROSSWALK_COMPILED_CSV).",
    )
    parser.add_argument(
        "--denue", default=None,
        help="Ruta a un DENUE real. Si se provee, se compila y persiste crosswalk_compiled.csv "
             "contra los códigos SCIAN observados en él. Si se omite, el script se detiene tras "
             "migrar y validar el activo de autoría.",
    )
    args = parser.parse_args()

    # 1) Crosswalk_Maestro.csv → AUTHORING_SCHEMA (activo editable)
    build_authoring_csv_from_master(
        master_csv_path=args.master,
        sectores_csv_path=SERIO_SECTORES_CSV,
        output_path=args.authoring_out,
        crosswalk_version=CROSSWALK_VERSION,
        scian_version=SCIAN_VERSION,
        serio_version=SERIO_VERSION,
        generated_by="scripts/build_crosswalk_maestro.py",
    )

    serio_codes, _ = load_serio_catalog(SERIO_SECTORES_CSV)
    builder = CrosswalkBuilder(serio_sectors=serio_codes)

    # 2) validate_authoring()
    authoring_df = builder.load_authoring(args.authoring_out)
    authoring_df, report = builder.validate_authoring(authoring_df)
    print(report.summary())

    if args.denue is None:
        print(
            "\nNo se proveyó --denue: el activo de autoría quedó migrado y validado en "
            f"{args.authoring_out}. Vuelve a ejecutar con --denue <ruta> para compilar y "
            f"persistir {args.compiled_out}."
        )
        return 0

    # 3) compile_to_flat_lookup() → crosswalk_compiled.csv
    denue_gdf = DENUELoader().run(args.denue)["normalized"]
    observed_codes = denue_gdf["scian"].dropna().astype(str).str.strip().unique().tolist()

    compiled = builder.compile_to_flat_lookup(authoring_df, observed_scian_codes=observed_codes)
    builder.save_compiled_lookup(compiled, args.compiled_out)
    print(f"\ncrosswalk_compiled.csv generado en {args.compiled_out} ({len(compiled)} filas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
