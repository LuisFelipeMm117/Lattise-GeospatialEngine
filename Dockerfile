# Dockerfile — Lattise Geospatial Engine, API REST (Stage 10)
#
# Contenedor mínimo para desplegar únicamente `api/` + el motor que
# consume (`spatial/`, `serio/`) en Railway. Deliberadamente NO incluye
# `app/` (Lattise Studio, Streamlit) — la API y el Studio son procesos
# distintos; si se necesita desplegar Streamlit también, usar un
# segundo Dockerfile/servicio (`Dockerfile.studio`) en vez de mezclar
# ambos en la misma imagen.
#
# Build:
#   docker build -t lattise-api .
# Run local:
#   docker run -p 8000:8000 -e PORT=8000 lattise-api

FROM python:3.12-slim

# geopandas/shapely/pyproj necesitan GDAL/GEOS/PROJ del sistema.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias primero (cache de capas de Docker).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código + artefactos de datos que la API necesita en disco.
# (Fase futura de la migración: reemplazar esta copia de `data/` y
# `serio/data/` por descarga desde R2 en el arranque — ver README,
# sección "Siguiente bloque de trabajo". Por ahora se empaquetan en la
# imagen para tener un despliegue funcional de inmediato.)
COPY api/ ./api/
COPY spatial/ ./spatial/
COPY serio/ ./serio/
COPY scripts/bootstrap_artifacts.py ./scripts/bootstrap_artifacts.py
RUN rm -rf ./serio/data ./data

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    LATTISE_ARTIFACTS_DIR=/var/lib/lattise/artifacts

EXPOSE 8000

CMD ["sh", "-c", "python scripts/bootstrap_artifacts.py && gunicorn -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:${PORT:-8000} --timeout 120 api.app:create_app()"]
