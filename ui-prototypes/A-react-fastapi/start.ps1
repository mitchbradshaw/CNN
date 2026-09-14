# One-command start for prototype A (React + TypeScript + FastAPI).
#   .\start.ps1            -> builds the client if needed, serves http://127.0.0.1:8765
#   .\start.ps1 -Dev       -> FastAPI on 8765 + Vite dev server on 5173 (proxy /api)
param([switch]$Dev, [int]$Port = 8765)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "creating project-local venv (system-site-packages) and installing fastapi/uvicorn"
  & "C:\ProgramData\anaconda3\python.exe" -m venv --system-site-packages (Join-Path $here ".venv")
  & $py -m pip install --quiet fastapi "uvicorn[standard]"
}
$client = Join-Path $here "client"
if (-not (Test-Path (Join-Path $client "node_modules"))) { Push-Location $client; npm install --no-audit --no-fund; Pop-Location }
if ($Dev) {
  Start-Process -NoNewWindow -FilePath $py -ArgumentList "`"$here\run_server.py`" --port $Port"
  Push-Location $client; npm run dev; Pop-Location
} else {
  if (-not (Test-Path (Join-Path $client "dist\index.html"))) { Push-Location $client; npm run build; Pop-Location }
  & $py (Join-Path $here "run_server.py") --port $Port
}
