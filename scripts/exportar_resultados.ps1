# ---------------------------------------------------------------------------
# Exporta desde Databricks los notebooks YA EJECUTADOS (con tablas, mapas y gráficos)
# para publicarlos en GitHub. El Git folder de Databricks no guarda los resultados de
# las celdas (política del workspace); la exportación con la CLI sí los incluye.
#
# Uso (desde la raíz del repo, en PowerShell):
#   .\scripts\exportar_resultados.ps1
#
# Genera:
#   resultados\notebooks_ejecutados\*.ipynb   GitHub los muestra con todas sus salidas
#   resultados\html\*.html                    versión para abrir en cualquier navegador
#   docs\figuras\*.png                        figuras guardadas por los notebooks
# ---------------------------------------------------------------------------
param(
    [string]$CliProfile = "mdd",
    [string]$Catalog = "workspace",
    [string]$Schema = "madre_dios_rs",
    [string]$Volume = "raw"
)

$ErrorActionPreference = "Stop"
$notebooks = @(
    "00_ingesta_cloud_bronze",
    "01_silver_compuestos_spark",
    "02_gold_h3_y_aede",
    "03_dependencia_espacial",
    "04_variograma_y_kriging",
    "05_patrones_puntuales",
    "06_regresion_espacial_y_ml"
)

$me = (databricks current-user me --profile $CliProfile -o json | ConvertFrom-Json).userName
if (-not $me) { Write-Host "No se pudo autenticar con el perfil $CliProfile" -ForegroundColor Red; exit 1 }
$src = "/Workspace/Users/$me/teledeteccion-cloud-madre-de-dios/notebooks"

New-Item -ItemType Directory -Force -Path "resultados\notebooks_ejecutados", "resultados\html", "docs\figuras" | Out-Null

foreach ($nb in $notebooks) {
    foreach ($fmt in @(@{f = "JUPYTER"; ext = "ipynb"; dir = "resultados\notebooks_ejecutados"},
                       @{f = "HTML"; ext = "html"; dir = "resultados\html"})) {
        $out = Join-Path $fmt.dir "$nb.$($fmt.ext)"
        if (Test-Path $out) { Remove-Item $out }
        databricks workspace export "$src/$nb" --format $fmt.f --file $out --profile $CliProfile 2>$null
        if ($LASTEXITCODE -ne 0) {
            # En algunos Git folders el notebook conserva la extensión .ipynb en su ruta
            databricks workspace export "$src/$nb.ipynb" --format $fmt.f --file $out --profile $CliProfile
        }
        if (Test-Path $out) {
            $mb = [math]::Round((Get-Item $out).Length / 1MB, 2)
            Write-Host ("  {0,-45} {1,6} MB" -f $out, $mb)
        } else {
            Write-Host "  No se pudo exportar $nb ($($fmt.f))" -ForegroundColor Yellow
        }
    }
}

Write-Host "Figuras del Volume -> docs\figuras" -ForegroundColor Cyan
databricks fs cp -r --overwrite "dbfs:/Volumes/$Catalog/$Schema/$Volume/figures" ".\docs\figuras" --profile $CliProfile

Write-Host "`nListo. Revisa con 'git status' y luego haz commit y push." -ForegroundColor Green
