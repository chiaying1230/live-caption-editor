$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$existing = $null
try { $existing = Invoke-RestMethod 'http://127.0.0.1:8001/api/health' -TimeoutSec 2 } catch { }
if ($existing) {
    if ($existing.backend -ne 'funasr') { throw 'Port 8001 is in use by another service. Stop that service first.' }
    Write-Host 'FunASR is already running. Open http://127.0.0.1:8001' -ForegroundColor Green
    exit 0
}
# A short path avoids MAX_PATH failures in PyTorch's third-party license files.
$environmentRoot = $env:CAPTION_FUNASR_ENV
if (-not $environmentRoot) {
    # Use the physical local Documents folder, not OneDrive Known Folder redirection.
    $environmentRoot = Join-Path $env:USERPROFILE 'Documents\Codex\work\live-caption-funasr'
}
$python = Join-Path $environmentRoot 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,14), 'Use Python 3.11-3.13'"
    if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.11-3.13 and add it to PATH.' }
    & python -m venv $environmentRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the separate FunASR environment.' }
}
$dependencyHash = (& $python -c "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('pyproject.toml').read_bytes()).hexdigest())").Trim()
$marker = Join-Path $environmentRoot 'caption-funasr-deps.sha256'
if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $dependencyHash) {
    & $python -m pip install --no-compile torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
    & $python -m pip install --no-compile -e '.[funasr]'
    if ($LASTEXITCODE -ne 0) { throw 'FunASR installation failed. Check the network and Python version.' }
    Set-Content -LiteralPath $marker -Value $dependencyHash -Encoding ASCII
}
$env:ASR_BACKEND = 'funasr'
if (-not $env:FUNASR_PREVIEW_MODE) { $env:FUNASR_PREVIEW_MODE = 'context' }
$env:CAPTION_PORT = '8001'
$env:DATA_DIR = 'data-funasr'
Write-Host 'Open http://127.0.0.1:8001 in Chrome or Edge.' -ForegroundColor Green
Write-Host 'This uses a separate database. Your Whisper transcripts remain on port 8000.'
Write-Host 'The first capture prepares the caption models. Keep this window open.'
& $python -m caption
