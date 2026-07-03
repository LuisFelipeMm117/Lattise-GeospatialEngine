# spatial/warehouse/denue_loader.py
"""
DENUELoader — PENDIENTE (siguiente bloque de trabajo).

Responsabilidad (Especificación v3.0, Stage 2-3):
    - Ingesta del DENUE (INEGI): CSV con lat/lon, SCIAN, nombre de unidad.
    - Limpieza de coordenadas nulas/erróneas (mismo principio que
      AGEBLoader.validate(): etiquetar, no descartar en silencio).
    - Homologación de tipos y estandarización de columnas en minúsculas.

Contrato de salida esperado: DataFrame con columnas mínimas
    ['id_unidad', 'scian', 'lon', 'lat', 'empleo', 'valid_coords']
listo para el Spatial Join de Stage 4 (integration & spatial index layer)
usando STRtree contra el GeoDataFrame normalizado de AGEBLoader.

No implementado todavía — ver ageb_loader.py como referencia de patrón
(validate() explícito y separado de normalize()).
"""


class DENUELoader:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "DENUELoader se construirá en el siguiente bloque de trabajo, "
            "siguiendo el mismo patrón de AGEBLoader (validate/normalize separados)."
        )
