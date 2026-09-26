$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Read application version from pstbskx\__init__.py so the release ZIP name
# follows the source version automatically.
$VersionFile = Join-Path $Root "pstbskx\__init__.py"
$VersionLine = Get-Content $VersionFile | Where-Object { $_ -match '^VERSION\s*=\s*"([^"]+)"' } | Select-Object -First 1
if (-not $VersionLine) {
    throw "VERSION was not found in pstbskx\__init__.py"
}
$Version = [regex]::Match($VersionLine, '^VERSION\s*=\s*"([^"]+)"').Groups[1].Value

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed" }

if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }

python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name "PSTBSK-X" `
  --icon "resources\pstbskx.ico" `
  --add-data "resources\pstbskx.png;resources" `
  main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# Stage the distributable folder.  When extracted from the ZIP, its root is:
# PSTBSK-X.exe + config/log/bak/licenses folders.
$OutName = "PSTBSK-X_${Version}_win64"
$Out = Join-Path $Root "dist\$OutName"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Move-Item -Force "dist\PSTBSK-X.exe" "$Out\PSTBSK-X.exe"
New-Item -ItemType Directory -Force -Path "$Out\config","$Out\log","$Out\bak","$Out\licenses" | Out-Null
Copy-Item "licenses\TBSKmodem_LICENSE.txt" "$Out\licenses\TBSKmodem_LICENSE.txt" -Force
python -c "from pathlib import Path; from pstbskx.updater import create_manifest; create_manifest(Path(r'$Out'), '$Version')"
if ($LASTEXITCODE -ne 0) { throw "Release manifest generation failed" }

# Create the actual release artifact as a ZIP under release\.
$ReleaseDir = Join-Path $Root "release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$ReleaseZip = Join-Path $ReleaseDir "$OutName.zip"
if (Test-Path $ReleaseZip) { Remove-Item $ReleaseZip -Force }
Compress-Archive -Path "$Out\*" -DestinationPath $ReleaseZip -CompressionLevel Optimal

Write-Host ""
Write-Host "Build complete"
Write-Host "  Staging : $Out"
Write-Host "  Release : $ReleaseZip"
