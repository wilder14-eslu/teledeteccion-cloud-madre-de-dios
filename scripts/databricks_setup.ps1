# ---------------------------------------------------------------------------
# Despliegue en Databricks con la CLI: catálogo, Volume, zona landing y repositorio.
# Requiere: Databricks CLI >= 0.205  (winget install Databricks.DatabricksCLI)
#
# Uso (desde la raíz del repo, en PowerShell):
#   .\scripts\databricks_setup.ps1 -WorkspaceUrl "https://<workspace>.cloud.databricks.com" `
#        -RepoUrl "https://github.com/wilder14-eslu/teledeteccion-cloud-madre-de-dios"
#
#   -SubirBronze  sube además data\bronze (solo si se usó el plan B de descarga local)
# ---------------------------------------------------------------------------
param(
    [Parameter(Mandatory = $true)][string]$WorkspaceUrl,
    [string]$RepoUrl = "",
    [string]$Catalog = "workspace",
    [string]$Schema = "madre_dios_rs",
    [string]$Volume = "raw",
    [string]$CliProfile = "mdd",
    [switch]$SubirBronze
)

$ErrorActionPreference = "Stop"
$base = "dbfs:/Volumes/$Catalog/$Schema/$Volume"

Write-Host "1) Autenticación OAuth (se abre el navegador)" -ForegroundColor Cyan
databricks auth login --host $WorkspaceUrl --profile $CliProfile

Write-Host "2) Esquema y Volume en Unity Catalog" -ForegroundColor Cyan
databricks schemas create $Schema $Catalog --profile $CliProfile 2>$null
databricks volumes create $Catalog $Schema $Volume MANAGED --profile $CliProfile 2>$null

Write-Host "3) Subiendo la zona landing (fuentes oficiales tal como se descargaron)" -ForegroundColor Cyan
databricks fs cp -r --overwrite ".\data\landing" "$base/landing" --profile $CliProfile
databricks fs ls "$base/landing" --profile $CliProfile

if ($SubirBronze) {
    Write-Host "3b) Plan B: subiendo data\bronze descargado localmente" -ForegroundColor Yellow
    databricks fs cp -r --overwrite ".\data\bronze" "$base/bronze" --profile $CliProfile
}

if ($RepoUrl -ne "") {
    Write-Host "4) Git folder con el repositorio (notebooks + src)" -ForegroundColor Cyan
    $me = (databricks current-user me --profile $CliProfile -o json | ConvertFrom-Json).userName
    $path = "/Workspace/Users/$me/teledeteccion-cloud-madre-de-dios"
    databricks repos create $RepoUrl gitHub --path $path --profile $CliProfile
    Write-Host "Repositorio en $path" -ForegroundColor Green
}

Write-Host "Listo. Ejecuta notebooks/00_ingesta_cloud_bronze en Databricks (cómputo serverless)." -ForegroundColor Green
