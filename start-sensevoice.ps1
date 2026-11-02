$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$existing = $null
try { $existing = Invoke-RestMethod 'http://127.0.0.1:8002/api/health' -TimeoutSec 2 } catch { }
if ($existing) {
    if ($existing.backend -ne 'sensevoice') { throw 'Port 8002 is in use by another service.' }
    Write-Host 'SenseVoice is already running. Open http://127.0.0.1:8002' -ForegroundColor Green
    exit 0
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,14), 'Use Python 3.11-3.13'"
    if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.11-3.13 and add it to PATH.' }
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$dependencyHash = (& $python -c "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('pyproject.toml').read_bytes()).hexdigest())").Trim()
$marker = Join-Path $PSScriptRoot '.venv\caption-sensevoice-deps.sha256'
if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $dependencyHash) {
    & $python -m pip install --no-compile -e '.[sensevoice]'
    if ($LASTEXITCODE -ne 0) { throw 'SenseVoice installation failed. Check the network and Python version.' }
    Set-Content -LiteralPath $marker -Value $dependencyHash -Encoding ASCII
}
$env:ASR_BACKEND = 'sensevoice'
$env:CAPTION_PORT = '8002'
$env:DATA_DIR = 'data-sensevoice'
Write-Host 'Open http://127.0.0.1:8002 in Chrome or Edge.' -ForegroundColor Green
Write-Host 'Use one microphone capture at a time. Existing transcripts stay on their original port.'
Write-Host 'The first capture downloads the ~240 MB model. Keep this window open.'
& $python -m caption
