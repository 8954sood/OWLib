$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$work = Join-Path $env:RUNNER_TEMP 'owlib-audio-dependencies'
New-Item -ItemType Directory -Force $work | Out-Null
$dependencies = @(
    @{
        Name = 'vgmstream'
        Url = 'https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win.zip'
        Hash = '4fa8f0f567a3636e45931b8462a04898fbceca17290a1458b80063b9558b323b'
        Destination = 'DataTool/Third Party/vgmstream-win'
    },
    @{
        Name = 'ffmpeg'
        Url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-23-13-04/ffmpeg-n8.1.3-24-g92611900bb-win64-gpl-8.1.zip'
        Hash = 'ec297d65145f71686498436bb7d5281f540d26fb6791072ba73b194498581b22'
        Destination = 'DataTool/Third Party/ffmpeg'
    }
)
foreach ($dependency in $dependencies) {
    $zip = Join-Path $work "$($dependency.Name).zip"
    Invoke-WebRequest $dependency.Url -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $dependency.Hash) { throw "Checksum mismatch: $($dependency.Name)" }
    $unpacked = Join-Path $work $dependency.Name
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force
    $source = $unpacked
    if ($dependency.Name -eq 'ffmpeg') { $source = (Get-ChildItem $unpacked -Directory | Select-Object -First 1).FullName }
    New-Item -ItemType Directory -Force $dependency.Destination | Out-Null
    Copy-Item "$source/*" $dependency.Destination -Recurse -Force
    "$($dependency.Url)`nSHA256: $($dependency.Hash)`nFFmpeg source/build recipes: https://github.com/BtbN/FFmpeg-Builds/tree/autobuild-2026-10-23-13-04`nFFmpeg source: https://github.com/FFmpeg/FFmpeg/commit/92611900bb" | Set-Content (Join-Path $dependency.Destination 'OWLib-PROVENANCE.txt')
}
