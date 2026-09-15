# One-command start for prototype B (Panel + Bokeh, in-process). Nothing to install: Panel 1.9.3 is in the conda env.
#   .\start.ps1 [-Port 8766]
param([int]$Port = 8766)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& "C:\ProgramData\anaconda3\python.exe" (Join-Path $here "run_app.py") --port $Port
