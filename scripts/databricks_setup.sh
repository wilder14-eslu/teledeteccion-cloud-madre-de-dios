#!/usr/bin/env bash
# Equivalente Linux/macOS de databricks_setup.ps1
# Uso: ./scripts/databricks_setup.sh https://<workspace>.cloud.databricks.com [repo_url] [--subir-bronze]
set -euo pipefail
HOST="$1"; REPO_URL="${2:-}"; SUBIR_BRONZE="${3:-}"
CATALOG=workspace; SCHEMA=madre_dios_rs; VOLUME=raw; PROFILE=mdd
BASE="dbfs:/Volumes/$CATALOG/$SCHEMA/$VOLUME"

databricks auth login --host "$HOST" --profile "$PROFILE"
databricks schemas create "$SCHEMA" "$CATALOG" --profile "$PROFILE" || true
databricks volumes create "$CATALOG" "$SCHEMA" "$VOLUME" MANAGED --profile "$PROFILE" || true
databricks fs cp -r --overwrite ./data/landing "$BASE/landing" --profile "$PROFILE"
[ "$SUBIR_BRONZE" = "--subir-bronze" ] && databricks fs cp -r --overwrite ./data/bronze "$BASE/bronze" --profile "$PROFILE"

if [ -n "$REPO_URL" ]; then
  ME=$(databricks current-user me --profile "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['userName'])")
  databricks repos create "$REPO_URL" gitHub --path "/Workspace/Users/$ME/teledeteccion-cloud-madre-de-dios" --profile "$PROFILE"
fi
echo "Listo."
