# spatial/warehouse/builder.py
"""
Orquestador del Spatial Economic Warehouse — PENDIENTE.

Responsabilidad (Especificación v3.0, Stage 5):
    Ensamblar AGEBLoader + DENUELoader + CrosswalkBuilder en la unidad
    de observación atómica W = {(g, s)}, calcular los pesos ω_{g,s} y
    serializar warehouse.parquet + metadata.json (Versioned Outputs).

Depende de:
    - spatial.warehouse.ageb_loader.AGEBLoader   (LISTO)
    - spatial.warehouse.denue_loader.DENUELoader (pendiente)
    - spatial.warehouse.crosswalk.CrosswalkBuilder (pendiente)

No implementado todavía.
"""


def build_warehouse(*args, **kwargs):
    raise NotImplementedError(
        "build_warehouse() se implementa una vez que DENUELoader y "
        "CrosswalkBuilder estén listos (Stage 4 es su prerrequisito directo)."
    )
