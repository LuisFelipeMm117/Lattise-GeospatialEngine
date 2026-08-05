# Artefactos externos de producción

El código se despliega sin `data/` ni `serio/data/`. Esos artefactos son un
bundle inmutable versionado, separado de la imagen de la API.

## Crear y publicar un bundle

Desde un checkout que tenga los artefactos reales:

```bash
python scripts/package_artifacts.py --output dist/lattise-artifacts-v1.zip
```

El comando imprime el SHA-256. Publique el archivo ZIP en Cloudflare R2 o en
un CDN con acceso privado/URL firmada. El ZIP contiene únicamente:

- `data/warehouse/`
- `data/analytics/`
- `data/graph/`
- `serio/data/`

No contiene `data/raw/`, cachés ni resultados temporales.

## Configurar el servicio

Configure estas variables como secretos del servicio:

```text
LATTISE_ARTIFACTS_DIR=/var/lib/lattise/artifacts
LATTISE_ARTIFACT_BUNDLE_URL=https://<dominio-o-url-firmada>/lattise-artifacts-v1.zip
LATTISE_ARTIFACT_BUNDLE_SHA256=<sha256-del-zip>
```

Monte `LATTISE_ARTIFACTS_DIR` en un volumen persistente. En el primer arranque
`scripts/bootstrap_artifacts.py` descarga, valida y publica el bundle de forma
atómica; en los siguientes no vuelve a descargarlo si el conjunto está completo.

Un checksum inválido, un ZIP incompleto o una ruta insegura abortan el arranque.
Esto evita servir una versión parcial o no verificada de los datos.
