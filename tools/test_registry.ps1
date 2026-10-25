$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$build = Join-Path $project 'build\registry-probe'
$vsRoot = & (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe") -latest -products '*' -property installationPath
if (!$vsRoot) { throw 'Visual Studio x86 C++ toolchain is required.' }
$msvc = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC\Tools\MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10")
$sdkVersion = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$compiler = Join-Path $msvc.FullName 'bin\Hostx64\x86\cl.exe'
$env:INCLUDE = "$($msvc.FullName)\include;$sdkRoot\Include\$($sdkVersion.Name)\ucrt;$sdkRoot\Include\$($sdkVersion.Name)\shared;$sdkRoot\Include\$($sdkVersion.Name)\um"
$env:LIB = "$($msvc.FullName)\lib\x86;$sdkRoot\Lib\$($sdkVersion.Name)\ucrt\x86;$sdkRoot\Lib\$($sdkVersion.Name)\um\x86"
$env:PATH = "$sdkRoot\bin\$($sdkVersion.Name)\x64;$($msvc.FullName)\bin\Hostx64\x86;$env:PATH"
New-Item -ItemType Directory -Path $build -Force | Out-Null
$executable = Join-Path $build 'registry-probe.exe'
& $compiler /nologo /W4 /std:c11 /Od (Join-Path $project 'tests\registry_probe.c') "/Fo$build\registry_probe.obj" "/Fe$executable" /link /MACHINE:X86 /MANIFEST:EMBED /MANIFESTUAC:NO advapi32.lib *> (Join-Path $build 'compile.log')
if ($LASTEXITCODE) { Get-Content -LiteralPath (Join-Path $build 'compile.log'); throw 'Registry probe compilation failed.' }
& $executable | Tee-Object -FilePath (Join-Path $build 'result.txt')
if ($LASTEXITCODE) { throw "Registry probe failed with exit code $LASTEXITCODE." }
