$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$expected = '129f977b604b2576bfd048e0f2be8b44ee983f39'
$actual = (git -C TACTLib rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actual -ne $expected) { throw "Unexpected TACTLib base: $actual; expected $expected" }
git -C TACTLib apply --check ../patches/tactlib-154504.patch
if ($LASTEXITCODE -ne 0) { throw 'TACTLib patch check failed (already applied or changed source)' }
git -C TACTLib apply ../patches/tactlib-154504.patch
if ($LASTEXITCODE -ne 0) { throw 'TACTLib patch failed' }
Write-Host 'Applied reviewed patch from sandsand244263/TACTLib@9b333b84211a4b95928e01be303b5ed27729c0aa'
