$ErrorActionPreference = "Stop"
if (-not $env:SHINE_API_KEY) { Write-Error "SHINE_API_KEY is not set in this PowerShell process."; exit 2 }
$headers = @{ Authorization = "Bearer $env:SHINE_API_KEY" }
try {
  $r = Invoke-RestMethod -Uri "https://api.shineshop.dev/v1/models" -Headers $headers -Method Get -TimeoutSec 30
  if (-not $r.data) { Write-Error "Response did not contain data[]."; exit 3 }
  Write-Host "Exact model IDs returned by SHINE SHOP:"
  $r.data | ForEach-Object { if ($_.id) { Write-Output $_.id } }
} catch { Write-Error ("Failed to list SHINE SHOP models: " + $_.Exception.Message); exit 4 }
