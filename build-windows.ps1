# Compatibility entry point. windows.ps1 builds, signs, verifies and packages.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "windows.ps1") @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
