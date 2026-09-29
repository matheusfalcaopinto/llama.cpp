param([ValidateRange(1024,65535)][int]$Port = 8765, [string]$Bind = '0.0.0.0', [switch]$NoBrowser, [switch]$Build)
$ErrorActionPreference = 'Stop'
$studioRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $studioRoot
$pythonPath = Join-Path $studioRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Instale uv (https://docs.astral.sh/uv/) e execute novamente.' }
    & uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependencias Python.' }
}
if ($Build -or -not (Test-Path -LiteralPath (Join-Path $studioRoot 'dist\index.html'))) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Instale Node.js 22 ou superior para compilar a interface.' }
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependencias da interface.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar a interface.' }
}
$url = "http://127.0.0.1:$Port"
$existing = $null
try { $existing = Invoke-RestMethod "$url/api/health" -TimeoutSec 2 } catch {}
if ($existing -and $existing.application -ne 'decision-studio') { throw "A porta $Port esta ocupada por outra aplicacao." }
if (-not $existing) {
    $logDir = Join-Path $studioRoot 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $proc = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.app:app','--host',$Bind,'--port',"$Port",'--workers','1') -WorkingDirectory $studioRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "studio-$Port.out.log") -RedirectStandardError (Join-Path $logDir "studio-$Port.err.log")
    @{id=$proc.Id; executable=$proc.Path; started=$proc.StartTime.ToUniversalTime().ToString('o'); port=$Port} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir "studio-$Port.pid.json") -Encoding UTF8
    $ready = $false
    for ($i=0; $i -lt 40; $i++) {
        if ($proc.HasExited) { throw "O servidor encerrou. Consulte logs\studio-$Port.err.log." }
        try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2; if ($health.application -eq 'decision-studio') { $ready=$true; break } } catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw 'O servidor ainda nao respondeu. Consulte os logs antes de tentar novamente.' }
}
Write-Host "Decision Studio: $url"
if ($Bind -eq '0.0.0.0') {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' -and $_.AddressState -eq 'Preferred' } | ForEach-Object { Write-Host "LAN ($($_.InterfaceAlias)): http://$($_.IPAddress):$Port" }
}
Write-Host 'Encerrar: stop.bat. O processo continua ativo ao fechar esta janela.'
if (-not $NoBrowser) { Start-Process $url }
