$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$vsRoot = & (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe") -latest -products '*' -property installationPath
$msvc = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC\Tools\MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10")
$sdkVersion = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$env:INCLUDE = "$($msvc.FullName)\include;$sdkRoot\Include\$($sdkVersion.Name)\ucrt;$sdkRoot\Include\$($sdkVersion.Name)\shared;$sdkRoot\Include\$($sdkVersion.Name)\um"
$env:LIB = "$($msvc.FullName)\lib\x86;$sdkRoot\Lib\$($sdkVersion.Name)\ucrt\x86;$sdkRoot\Lib\$($sdkVersion.Name)\um\x86"
$compiler = Join-Path $msvc.FullName 'bin\Hostx64\x86\cl.exe'
New-Item -ItemType Directory -Force -Path build/native-ui/backend | Out-Null
& python tools/patch_native_menu.py | Out-File -LiteralPath build/native-ui/generate.log -Encoding utf8
if ($LASTEXITCODE) { throw 'Menu/profile generation failed' }
& $compiler /nologo /c /O2 /W4 /WX /std:c++17 /EHsc /Fobuild/native-ui/backend/settings_regex.obj native/settings_regex.cpp
if ($LASTEXITCODE) { throw 'Settings regex compilation failed' }
& $compiler /nologo /O2 /W4 /WX /std:c++17 /EHsc /Febuild/native-ui/backend/settings-regex-probe.exe /Fobuild/native-ui/backend/ tests/settings_regex_probe.cpp build/native-ui/backend/settings_regex.obj
if ($LASTEXITCODE) { throw 'Settings regex probe compilation failed' }
& $compiler /nologo /O2 /W4 /WX /std:c11 /DVOID_SETTINGS_TEST /D_CRT_SECURE_NO_WARNINGS /Ibuild/native-ui /Fobuild/native-ui/backend/ /Febuild/native-ui/backend/settings-debug-probe.exe native/settings_debug.c tests/settings_debug_probe.c build/native-ui/backend/settings_regex.obj /link /MACHINE:X86 kernel32.lib
if ($LASTEXITCODE) { throw 'Settings backend compilation failed' }
& python tests/test_settings_debug.py
if ($LASTEXITCODE) { throw 'Settings backend tests failed' }
