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
#   poster\data\                              paquete liviano del póster web (notebook 07):
#                                              h3_poster.parquet, capas\*.geojson, resumen.json,
#                                              modelo\ (Random Forest de MLflow y zona de demostración)
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
    "06_regresion_espacial_y_ml",
    "07_exportar_poster"
)

$me = (databricks current-user me --profile $CliProfile -o json | ConvertFrom-Json).userName
if (-not $me) { Write-Host "No se pudo autenticar con el perfil $CliProfile" -ForegroundColor Red; exit 1 }
$src = "/Workspace/Users/$me/teledeteccion-cloud-madre-de-dios/notebooks"

New-Item -ItemType Directory -Force -Path "resultados\notebooks_ejecutados", "resultados\html", "docs\figuras" | Out-Null

# Rutas reales de los notebooks en el Git folder (con o sin extensión .ipynb)
$listado = databricks workspace list $src -o json --profile $CliProfile | ConvertFrom-Json
if (-not $listado) { Write-Host "No se pudo listar $src" -ForegroundColor Red; exit 1 }
$tmpDir = Join-Path $env:TEMP "export_dbx"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

foreach ($nb in $notebooks) {
    $obj = $listado | Where-Object { (Split-Path $_.path -Leaf) -in @($nb, "$nb.ipynb", "$nb.py") } | Select-Object -First 1
    if (-not $obj) {
        Write-Host "  $nb no está en $src (¿hiciste Pull en el Git folder?)" -ForegroundColor Yellow
        continue
    }
    foreach ($fmt in @(@{f = "JUPYTER"; ext = "ipynb"; dir = "resultados\notebooks_ejecutados"},
                       @{f = "HTML"; ext = "html"; dir = "resultados\html"})) {
        $out = Join-Path $fmt.dir "$nb.$($fmt.ext)"
        $tmp = Join-Path $tmpDir "$nb.$($fmt.ext)"
        if (Test-Path $tmp) { Remove-Item $tmp }
        $err = databricks workspace export $obj.path --format $fmt.f --file $tmp --profile $CliProfile 2>&1
        if ($LASTEXITCODE -eq 0 -and (Test-Path $tmp)) {
            Move-Item $tmp $out -Force          # solo se reemplaza la versión anterior si la exportación funcionó
            $mb = [math]::Round((Get-Item $out).Length / 1MB, 2)
            Write-Host ("  {0,-45} {1,6} MB" -f $out, $mb)
        } else {
            Write-Host "  No se pudo exportar $nb ($($fmt.f)); se conserva la versión anterior. $err" -ForegroundColor Yellow
        }
    }
}

Write-Host "Figuras del Volume -> docs\figuras" -ForegroundColor Cyan
databricks fs cp -r --overwrite "dbfs:/Volumes/$Catalog/$Schema/$Volume/figures" ".\docs\figuras" --profile $CliProfile

Write-Host "Datos del póster web -> poster\data" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "poster\data" | Out-Null
databricks fs cp -r --overwrite "dbfs:/Volumes/$Catalog/$Schema/$Volume/poster" ".\poster\data" --profile $CliProfile
if (Test-Path "poster\data\h3_poster.parquet") {
    Get-ChildItem "poster\data" -Recurse -File | ForEach-Object {
        Write-Host ("  {0,-45} {1,8} kB" -f $_.FullName.Replace((Get-Location).Path + "\", ""), [math]::Round($_.Length / 1KB, 1))
    }
} else {
    Write-Host "  No se encontró poster/h3_poster.parquet en el Volume: ejecuta antes el notebook 07." -ForegroundColor Yellow
}

# El modelo se serializó con versiones concretas de scikit-learn y numpy: se fijan las mismas en el póster
$metaFile = "poster\data\modelo\modelo_meta.json"
if (Test-Path $metaFile) {
    $meta = Get-Content $metaFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $req = Get-Content "poster\requirements.txt" -Encoding UTF8
    $req = $req -replace '^scikit-learn.*', "scikit-learn==$($meta.sklearn)" -replace '^numpy.*', "numpy==$($meta.numpy)"
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines((Join-Path (Get-Location) "poster\requirements.txt"), $req, $utf8)
    Write-Host "  requirements del póster: scikit-learn==$($meta.sklearn), numpy==$($meta.numpy)"
}

Write-Host "`nListo. Revisa con 'git status' y luego haz commit y push." -ForegroundColor Green
