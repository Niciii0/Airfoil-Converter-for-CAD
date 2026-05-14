$ErrorActionPreference = "Stop"

Write-Host "Building Airfoil Converter V6.2..."

$python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $python -m PyInstaller --noconfirm "Airfoil Converter V6.2.spec"

Write-Host ""
Write-Host "Done. App folder:"
Write-Host "dist\Airfoil Converter V6.2"
