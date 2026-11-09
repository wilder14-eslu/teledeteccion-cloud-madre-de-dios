# ---------------------------------------------------------------------------
# Despliega la aplicación web (Databricks App con Streamlit) y le da acceso de
# solo lectura a las tablas Gold. Todo con la Databricks CLI.
#
# Uso (desde la raíz del repo, en PowerShell):
#   .\scripts\desplegar_app.ps1
#
# Pasos:
#   1. Busca el SQL Warehouse serverless del workspace
#   2. Crea la app (si no existe) con el warehouse como recurso
#   3. Sube el código de app/ al workspace y despliega
#   4. Otorga a la identidad de la app USE CATALOG, USE SCHEMA y SELECT
# ---------------------------------------------------------------------------
param(
    [string]$CliProfile = "mdd",
    [string]$AppName = "visor-mineria-mdd",
    [string]$WarehouseName = "Serverless Starter Warehouse",
    [string]$Catalog = "workspace",
    [string]$Schema = "madre_dios_rs"
)

$ErrorActionPreference = "Stop"
function Assert-Ok($paso) {
    if ($LASTEXITCODE -ne 0) { Write-Host "Falló: $paso" -ForegroundColor Red; exit 1 }
}
$tmp = Join-Path $env:TEMP "geocloud_app"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Write-Host "1) SQL Warehouse" -ForegroundColor Cyan
$wh = (databricks warehouses list --profile $CliProfile -o json | ConvertFrom-Json) |
      Where-Object { $_.name -eq $WarehouseName } | Select-Object -First 1
if (-not $wh) { Write-Host "No se encontró el warehouse '$WarehouseName'" -ForegroundColor Red; exit 1 }
Write-Host "   $($wh.name) ($($wh.id))"

Write-Host "2) App $AppName" -ForegroundColor Cyan
databricks apps get $AppName --profile $CliProfile -o json 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $cfg = @{
        name        = $AppName
        description = "Visor de minería aurífera y deforestación en Madre de Dios (tablas Gold de Unity Catalog)"
        resources   = @(@{ name = "sql-warehouse"; sql_warehouse = @{ id = $wh.id; permission = "CAN_USE" } })
    } | ConvertTo-Json -Depth 5
    $cfgFile = Join-Path $tmp "app.json"
    Set-Content -Path $cfgFile -Value $cfg -Encoding ascii
    Write-Host "   Creando la app (el cómputo de la app tarda 2-5 minutos en iniciar)..."
    databricks apps create --json "@$cfgFile" --profile $CliProfile
    Assert-Ok "creación de la app"
} else {
    Write-Host "   La app ya existe: se actualiza el código"
}

Write-Host "3) Subida del código y despliegue" -ForegroundColor Cyan
$me = (databricks current-user me --profile $CliProfile -o json | ConvertFrom-Json).userName
$dest = "/Workspace/Users/$me/apps/$AppName"
databricks sync .\app $dest --full --profile $CliProfile
Assert-Ok "sincronización del código"
databricks apps deploy $AppName --source-code-path $dest --profile $CliProfile
Assert-Ok "despliegue"

Write-Host "4) Permisos de lectura en Unity Catalog para la identidad de la app" -ForegroundColor Cyan
$app = databricks apps get $AppName --profile $CliProfile -o json | ConvertFrom-Json
$sp = $app.service_principal_client_id
foreach ($g in @(@{ tipo = "catalog"; nombre = $Catalog; priv = @("USE_CATALOG") },
                 @{ tipo = "schema"; nombre = "$Catalog.$Schema"; priv = @("USE_SCHEMA", "SELECT") })) {
    $body = @{ changes = @(@{ principal = $sp; add = $g.priv }) } | ConvertTo-Json -Depth 5
    $f = Join-Path $tmp "grant_$($g.tipo).json"
    Set-Content -Path $f -Value $body -Encoding ascii
    databricks grants update $g.tipo $g.nombre --json "@$f" --profile $CliProfile | Out-Null
    Assert-Ok "permisos sobre $($g.tipo) $($g.nombre)"
    Write-Host "   $($g.priv -join ', ') en $($g.tipo) $($g.nombre)"
}

Write-Host "`nListo. URL de la aplicación:" -ForegroundColor Green
Write-Host "   $($app.url)" -ForegroundColor Green
