# ---------------------------------------------------------------------------
# Configura Databricks con la CLI y sube la capa Bronze al Volume.
# Requiere: Databricks CLI >= 0.205  (winget install Databricks.DatabricksCLI)
#
# Uso (desde la raíz del repo, en PowerShell):
#   .\scripts\databricks_setup.ps1 -WorkspaceUrl "https://<tu-workspace>.cloud.databricks.com" -RepoUrl "https://github.com/<usuario>/teledeteccion-cloud-madre-de-dios"
# ---------------------------------------------------------------------------
param(
    [Parameter(Mandatory = $true)][string]$WorkspaceUrl,
    [string]$RepoUrl = "",
    [string]$Catalog = "workspace",
    [string]$Schema = "madre_dios_rs",
    [string]$Volume = "raw",
    [string]$CliProfile = "mdd"
)

$ErrorActionPreference = "Stop"

Write-Host "1) Autenticación OAuth (se abre el navegador)" -ForegroundColor Cyan
databricks auth login --host $WorkspaceUrl --profile $CliProfile

Write-Host "2) Esquema y Volume en Unity Catalog" -ForegroundColor Cyan
databricks schemas create $Schema $Catalog --profile $CliProfile 2>$null
databricks volumes create $Catalog $Schema $Volume MANAGED --profile $CliProfile 2>$null

Write-Host "3) Subiendo data/bronze al Volume (puede tardar según tu conexión)" -ForegroundColor Cyan
$dest = "dbfs:/Volumes/$Catalog/$Schema/$Volume/bronze"
databricks fs cp -r --overwrite ".\data\bronze" $dest --profile $CliProfile
databricks fs ls "dbfs:/Volumes/$Catalog/$Schema/$Volume/bronze" --profile $CliProfile

if ($RepoUrl -ne "") {
    Write-Host "4) Creando Git folder con el repositorio (notebooks + src)" -ForegroundColor Cyan
    $me = (databricks current-user me --profile $CliProfile -o json | ConvertFrom-Json).userName
    $path = "/Workspace/Users/$me/teledeteccion-cloud-madre-de-dios"
    databricks repos create $RepoUrl gitHub --path $path --profile $CliProfile
    Write-Host "Repositorio disponible en $path" -ForegroundColor Green
}

Write-Host "Listo. Abre notebooks/00_config_y_bronze en Databricks." -ForegroundColor Green
