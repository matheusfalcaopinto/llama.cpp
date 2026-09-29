param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$studioRoot = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $studioRoot "logs\studio-$Port.pid.json"
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'Nenhum processo registrado nesta pasta.'; exit 0 }
$saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$proc = Get-Process -Id $saved.id -ErrorAction SilentlyContinue
if (-not $proc) { Write-Host 'O processo ja foi encerrado.'; exit 0 }
$command = (Get-CimInstance Win32_Process -Filter "ProcessId = $($saved.id)").CommandLine
$savedStart = ([datetime]$saved.started).ToUniversalTime()
if ($proc.Path -ne $saved.executable -or $proc.StartTime.ToUniversalTime().Ticks -ne $savedStart.Ticks -or $command -notlike '*backend.app:app*') { throw 'A identidade do processo mudou; nenhum processo foi encerrado.' }
Stop-Process -Id $proc.Id
Write-Host 'Decision Studio encerrado. Arquivos e historico preservados.'
