# Requires Nuitka 2.3+ and Python 3.9+
# Usage: run from project root with PowerShell:  ./build_with_nuitka.ps1

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    $python = "python"

    Write-Host "Installing build dependencies (nuitka, ordered-set, zstandard) if missing..."
    & $python -m pip install --upgrade nuitka ordered-set zstandard | Out-Null

    $outputDir = Join-Path $projectRoot "dist"
    if (-not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }

    Write-Host "Running Nuitka onefile build..."
    & $python -m nuitka `
        --standalone `
        --show-progress --show-memory `
        --enable-plugin=pyqt5 `
        --mingw64 `
        --assume-yes-for-downloads `
        --windows-disable-console `
        --windows-company-name="Yserver" `
        --windows-product-name="GaodeAtlas" `
        --windows-file-version="1.0.0.0" `
        --windows-product-version="1.0" `
        --windows-file-description="GaodeAtlas" `
        --windows-icon-from-ico="favicon.ico" `
        --include-data-files="favicon.ico=favicon.ico" `
        --output-dir="$outputDir" `
        app.py
}
finally {
    Pop-Location
}
