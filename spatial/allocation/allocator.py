# spatial/allocation/allocator.py
"""
Allocation Engine — PENDIENTE (Stage 7).
Filtra warehouse.parquet por weight_type y distribuye ΔX (de
ModeloEconomico.simular()) usando ω_{g,s}, exportando shock_ageb.parquet (SSD).
"""


def allocate_shock(*args, **kwargs):
    raise NotImplementedError("Pendiente — depende de allocation/weights.py.")
