# spatial/graph/network.py
"""
Spatial Graph Builder — PENDIENTE.
Responsabilidad (Sección 4, Arquitectura de Componentes Desacoplados):
    Construir la matriz de pesos espaciales M (|G| x |G|) — contigüidad,
    distancia o accesibilidad inter-AGEB. NO pertenece al Warehouse (SEW);
    es un artefacto exógeno e independiente, análogo al patrón
    `libpysal.weights` ya usado en el MVP de propagación espacial de Lattise.
"""


def build_spatial_weights(*args, **kwargs):
    raise NotImplementedError("Se implementa tras cerrar warehouse/builder.py.")
