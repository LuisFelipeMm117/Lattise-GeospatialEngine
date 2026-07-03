# spatial/warehouse/crosswalk.py
"""
CrosswalkBuilder — PENDIENTE.

Responsabilidad (Especificación v3.0, Sección 6 — Unicidad del Mapeo
Sectorial): construir el mapeo biunívoco SCIAN → los 78 sectores del
modelo SERIO. Cualquier excepción de asignación múltiple debe quedar
registrada explícitamente aquí, no resuelta de forma implícita.

Insumo natural: modelo.sectores / modelo.sector_names de loader.py
(ModeloEconomico), ya que ese es el universo S de 78 sectores válido.
"""


class CrosswalkBuilder:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "CrosswalkBuilder se construirá junto con DENUELoader, ya que "
            "el crosswalk SCIAN→SERIO es insumo directo del Spatial Join (Stage 4)."
        )
