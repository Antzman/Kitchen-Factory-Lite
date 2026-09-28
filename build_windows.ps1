$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, release
python -m PyInstaller --clean --noconfirm KitchenFactory.spec

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $knownPath = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $knownPath) {
        $iscc = $knownPath
    }
}
if (-not $iscc) {
    Write-Warning "PyInstaller build completed. Install Inno Setup 6 and compile installer\KitchenFactory.iss to create KitchenFactorySetup.exe."
    exit 0
}

& $iscc.Source (Join-Path $PSScriptRoot "installer\KitchenFactory.iss")
Write-Host "Installer created at release\KitchenFactorySetup.exe"
