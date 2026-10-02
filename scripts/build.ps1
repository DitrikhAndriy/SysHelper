# Run from the project root: .\scripts\build.ps1
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    & py -m PyInstaller --noconfirm --clean --onefile --windowed --name SysHelper main.py
    if ($LASTEXITCODE -ne 0) {
        throw 'Build failed. Install Python and requirements-build.txt first.'
    }
    Write-Host 'Created dist\SysHelper.exe'
} finally {
    Pop-Location
}
