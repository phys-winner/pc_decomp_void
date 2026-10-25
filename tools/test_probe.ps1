param([switch]$Android, [string]$Serial = $env:ANDROID_SERIAL)
$ErrorActionPreference = 'Stop'
if ($Android -and !$Serial) { throw 'Android probe requires -Serial SERIAL or ANDROID_SERIAL.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& tools/fetch_dependencies.ps1
& python tools/lift_probe.py
if ($LASTEXITCODE) { throw 'Original x86 oracle failed' }
New-Item -ItemType Directory -Force -Path build/probe | Out-Null
$vsRoot = & (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe") -latest -products '*' -property installationPath
$msvc = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC\Tools\MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10")
$sdkVersion = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$env:INCLUDE = "$($msvc.FullName)\include;$sdkRoot\Include\$($sdkVersion.Name)\ucrt;$sdkRoot\Include\$($sdkVersion.Name)\shared;$sdkRoot\Include\$($sdkVersion.Name)\um"
$env:LIB = "$($msvc.FullName)\lib\x86;$sdkRoot\Lib\$($sdkVersion.Name)\ucrt\x86;$sdkRoot\Lib\$($sdkVersion.Name)\um\x86"
& (Join-Path $msvc.FullName 'bin\Hostx64\x86\cl.exe') /nologo /O2 /W3 /std:c11 /DRECOMP_FS_SIMULATED /Ireference/pcrecomp/runtime/recomp32_cpu /Igenerated/probe native/probe.c native/probe_main.c generated/probe/lifted.c /Fobuild/probe/ /Febuild/probe/void-probe-x86.exe /link /MACHINE:X86
if ($LASTEXITCODE) { throw 'x86 probe compilation failed' }
& build/probe/void-probe-x86.exe
if ($LASTEXITCODE) { throw 'Native x86 differential test failed' }
$proofReport = Get-Content -LiteralPath generated/probe/report.json -Raw | ConvertFrom-Json
$proofReport.native_x86 = 'PASS: original native x86 and lifted C compared on the same hardware'
if ($Android) {
    $ndkBin = Join-Path $env:LOCALAPPDATA 'Android\Sdk\ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin'
    $common = @('--target=aarch64-linux-android26', '-O2', '-std=c11', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror', '-Ireference/pcrecomp/runtime/recomp32_cpu', '-Igenerated/probe', 'native/probe.c', 'generated/probe/lifted.c', '-lm', '-Wl,-z,max-page-size=16384')
    & (Join-Path $ndkBin 'clang.exe') @common native/probe_main.c -o build/probe/void-probe-arm64
    if ($LASTEXITCODE) { throw 'ARM64 probe compilation failed' }
    & (Join-Path $ndkBin 'clang.exe') @common native/probe_jni.c -fPIC -shared -o build/probe/libvoidprobe.so
    if ($LASTEXITCODE) { throw 'JNI proof compilation failed' }
    & adb -s $Serial push build/probe/void-probe-arm64 /data/local/tmp/the-void-static-probe
    if ($LASTEXITCODE) { throw 'Cannot upload ARM64 probe' }
    & adb -s $Serial shell chmod 700 /data/local/tmp/the-void-static-probe
    if ($LASTEXITCODE) { throw 'Cannot mark ARM64 probe executable' }
    & adb -s $Serial shell /data/local/tmp/the-void-static-probe
    if ($LASTEXITCODE) { throw 'ARM64 differential test failed' }
    $proofReport.native_arm64 = 'PASS: standalone ARM64 on SERIAL; JNI embedding remains unaccepted'
}
$proofReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath generated/probe/report.json -Encoding utf8
