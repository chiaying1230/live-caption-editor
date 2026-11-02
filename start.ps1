$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) { throw 'Install 64-bit Python 3.11, 3.12 or 3.13 and enable Add Python to PATH.' }
    & python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,14), 'Use Python 3.11-3.13'"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11-3.13 is required.' }
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Check your Python installation.' }
}
$dependencyHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'pyproject.toml') -Algorithm SHA256).Hash
$marker = Join-Path $PSScriptRoot '.venv\project-deps.sha256'
if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $dependencyHash) {
    & $python -m pip install -e .
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and Python version.' }
    Set-Content -LiteralPath $marker -Value $dependencyHash -Encoding ASCII
}
Write-Host ''
Write-Host 'Open http://127.0.0.1:8000 in Chrome or Edge.' -ForegroundColor Green
Write-Host 'First capture downloads the Whisper model. Keep this window open.'
Write-Host 'Press Ctrl+C to stop the server.'
& $python -m caption
