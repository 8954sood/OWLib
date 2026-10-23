$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = Join-Path (Get-Location) 'dist/OWLib-Windows-154504'
foreach ($tool in @('DataTool', 'TankView')) {
    foreach ($file in @("$tool.exe", "$tool.runtimeconfig.json", 'coreclr.dll', 'hostfxr.dll', 'hostpolicy.dll', 'librevorb.dll', 'Third Party/packed_codebooks_aoTuV_603.bin', 'Static/audio-browser.html', 'Static/GUIDNames.csv')) {
        if (!(Test-Path (Join-Path $root "$tool/$file"))) { throw "Missing $tool/$file" }
    }
    $config = Get-Content (Join-Path $root "$tool/$tool.runtimeconfig.json") -Raw | ConvertFrom-Json
    if (!$config.runtimeOptions.includedFrameworks -or $config.runtimeOptions.frameworks -or $config.runtimeOptions.framework) { throw "$tool is not self-contained" }
}
$emptyRuntime = Join-Path $env:RUNNER_TEMP 'owlib-empty-dotnet'
New-Item -ItemType Directory -Force $emptyRuntime | Out-Null
$env:DOTNET_ROOT = $emptyRuntime
$env:DOTNET_ROOT_X64 = $emptyRuntime
$env:DOTNET_MULTILEVEL_LOOKUP = '0'
$env:DOTNET_ROLL_FORWARD = 'Disable'
$help = & "$root/DataTool/DataTool.exe" 'unused-game-path' 'extract-all-sounds' '--help' 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $help -notmatch 'extract-all-sounds') { throw "Self-contained help/registration failed: $help" }
Write-Host $help
$view = Start-Process -FilePath "$root/TankView/TankView.exe" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
$view.Refresh()
if ($view.HasExited -and $view.ExitCode -ne 0) { throw "TankView failed to start: $($view.ExitCode)" }
if (!$view.HasExited) { Stop-Process -Id $view.Id }
Write-Host 'PASS: self-contained publish files, DataTool help/registration, TankView process startup. Game extraction not tested.'
