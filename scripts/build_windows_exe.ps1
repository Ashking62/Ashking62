$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPath = Join-Path $ProjectRoot ".venv-build"
if (-not (Test-Path $VenvPath)) {
    py -3 -m venv $VenvPath
}

$Python = Join-Path $VenvPath "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt -r requirements-build.txt
& $Python -m PyInstaller --clean --noconfirm pdf_translator_fr.spec

$ExePath = Join-Path $ProjectRoot "dist\TraducteurPDF_FR.exe"
if (-not (Test-Path $ExePath)) {
    throw "Executable not found: $ExePath"
}

Write-Host "Executable created: $ExePath"
