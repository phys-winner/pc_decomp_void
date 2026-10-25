param([switch]$GameModule, [switch]$Engine, [switch]$Filesystems, [switch]$Sound, [switch]$Media, [switch]$Renderer, [switch]$NxCharacter)
$ErrorActionPreference = 'Stop'
if ($NxCharacter) { $Renderer = $true }
if ($Renderer) { $Media = $true }
if ($Media) { $Sound = $true }
if ($Sound) { $Filesystems = $true }
if ($Filesystems) { $Engine = $true }
if ($Engine) { $GameModule = $true }
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$vsRoot = & (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe") -latest -products '*' -property installationPath
if (!$vsRoot) { throw 'Visual Studio with the x86 C++ toolchain is required' }
$msvc = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC\Tools\MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10")
$sdkVersion = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$env:INCLUDE = "$($msvc.FullName)\include;$sdkRoot\Include\$($sdkVersion.Name)\ucrt;$sdkRoot\Include\$($sdkVersion.Name)\shared;$sdkRoot\Include\$($sdkVersion.Name)\um"
$env:LIB = "$($msvc.FullName)\lib\x86;$sdkRoot\Lib\$($sdkVersion.Name)\ucrt\x86;$sdkRoot\Lib\$($sdkVersion.Name)\um\x86"
$env:PATH = "$sdkRoot\bin\$($sdkVersion.Name)\x64;$($msvc.FullName)\bin\Hostx64\x86;$env:PATH"
$compiler = Join-Path $msvc.FullName 'bin\Hostx64\x86\cl.exe'
New-Item -ItemType Directory -Force -Path build/x86 | Out-Null
& python tools/prepare_native_runtime.py
if ($LASTEXITCODE) { throw 'Project native runtime preparation failed' }
& python tools/patch_native_menu.py
if ($LASTEXITCODE) { throw 'Native menu generation failed' }
& $compiler /nologo /O2 /W3 /std:c++17 /EHsc /D_CRT_SECURE_NO_WARNINGS /Inative /c native/settings_regex.cpp /Fobuild/x86/settings_regex.obj *> build/x86/compile-settings-regex.log
if ($LASTEXITCODE) { Get-Content -LiteralPath build/x86/compile-settings-regex.log; throw 'Native settings profile matcher compilation failed' }
& python tools/lift_game.py
if ($LASTEXITCODE) { throw 'Game.exe lifting failed' }
$report = Get-Content -LiteralPath generated/game-x86/report.json -Raw | ConvertFrom-Json
$sources = @('native/windows_host.c', 'native/window_policy.c', 'native/asset_overrides.c', 'native/settings_debug.c', 'build/x86/settings_regex.obj', 'native/void_runtime.c', 'reference/pcrecomp/runtime/recomp32/image_loader.c', 'reference/pcrecomp/runtime/recomp32/recomp_trace.c', 'generated/game-x86/recomp_dispatch.c')
for ($chunk = 0; $chunk -lt [Math]::Ceiling($report.functions / 100); $chunk++) {
    $sources += 'generated/game-x86/recomp_{0:D4}.c' -f $chunk
}
$outputName = 'void-x86'
$hostBase = '0x70000000'
$extraCompilerArguments = @('/Ibuild/native-ui')
if ($GameModule) {
    & python tools/lift_gamemodule.py
    if ($LASTEXITCODE) { throw 'GameModule lifting failed' }
    $moduleReport = Get-Content -LiteralPath generated/gamemodule-x86/report.json -Raw | ConvertFrom-Json
    $sources = @($sources | Where-Object { $_ -ne 'generated/game-x86/recomp_dispatch.c' })
    $sources += 'generated/gamemodule-x86/recomp_dispatch.c'
    for ($chunk = 0; $chunk -lt [Math]::Ceiling($moduleReport.functions / 100); $chunk++) {
        $sources += 'generated/gamemodule-x86/gamemodule_{0:D4}.c' -f $chunk
    }
    $extraCompilerArguments += '/DVOID_LIFT_GAMEMODULE', '/Igenerated/gamemodule-x86'
    $outputName = 'void-x86-gamemodule'
}
if ($Engine) {
    & python tools/lift_engine.py
    if ($LASTEXITCODE) { throw 'Engine lifting failed' }
    $engineReport = Get-Content -LiteralPath generated/engine-x86/report.json -Raw | ConvertFrom-Json
    $sources = @($sources | Where-Object { $_ -ne 'generated/gamemodule-x86/recomp_dispatch.c' })
    $sources += 'generated/engine-x86/recomp_dispatch.c'
    foreach ($source in $engineReport.sources) { $sources += "generated/engine-x86/$source" }
    $extraCompilerArguments += '/DVOID_LIFT_ENGINE', '/Igenerated/engine-x86'
    $outputName = 'void-x86-engine'
    # shortcut: MSVC 14.51 /O2 takes >20 minutes on this TU; remove after filtering its descriptor-data seed.
    $sizeOptimizedSource = 'generated/engine-x86/engine_0026.c'
    & $compiler /nologo /O1 /W0 /std:c11 /DRECOMP_TRACE /D_CRT_SECURE_NO_WARNINGS /Inative /Ireference/pcrecomp/runtime/recomp32 /Ireference/pcrecomp/runtime/native32 /Igenerated/game-x86 @extraCompilerArguments /c $sizeOptimizedSource /Fobuild/x86/engine_0026.obj *> build/x86/compile-engine-size.log
    if ($LASTEXITCODE) { Get-Content build/x86/compile-engine-size.log; throw 'Engine size-optimized compilation failed' }
    $sources = @($sources | Where-Object { $_ -ne $sizeOptimizedSource })
    $sources += 'build/x86/engine_0026.obj'
}
if ($Filesystems) {
    & python tools/lift_filesystems.py
    if ($LASTEXITCODE) { throw 'Filesystem lifting failed' }
    $sources = @($sources | Where-Object { $_ -ne 'generated/engine-x86/recomp_dispatch.c' })
    $sources += 'generated/vfs-x86/recomp_dispatch.c'
    foreach ($module in @('fs','vfs')) {
        $fileReport = Get-Content -LiteralPath "generated/$module-x86/report.json" -Raw | ConvertFrom-Json
        foreach ($source in $fileReport.sources) { $sources += "generated/$module-x86/$source" }
        $extraCompilerArguments += "/Igenerated/$module-x86"
    }
    $extraCompilerArguments += '/DVOID_LIFT_FILESYSTEMS'
    $outputName = 'void-x86-filesystems'
}
if ($Sound) {
    & python tools/lift_media.py
    if ($LASTEXITCODE) { throw 'Media lifting failed' }
    $sources = @($sources | Where-Object { $_ -ne 'generated/vfs-x86/recomp_dispatch.c' })
    $sources += 'generated/sound-x86/recomp_dispatch.c'
    foreach ($module in @('sound')) {
        $mediaReport = Get-Content -LiteralPath "generated/$module-x86/report.json" -Raw | ConvertFrom-Json
        foreach ($source in $mediaReport.sources) { $sources += "generated/$module-x86/$source" }
        $extraCompilerArguments += "/Igenerated/$module-x86"
    }
    $extraCompilerArguments += '/DVOID_LIFT_SOUND'
    $outputName = 'void-x86-sound'
}
if ($Media) {
    $sources = @($sources | Where-Object { $_ -ne 'generated/sound-x86/recomp_dispatch.c' })
    $sources += 'generated/video-x86/recomp_dispatch.c'
    $videoReport = Get-Content -LiteralPath 'generated/video-x86/report.json' -Raw | ConvertFrom-Json
    foreach ($source in $videoReport.sources) { $sources += "generated/video-x86/$source" }
    $extraCompilerArguments += '/DVOID_LIFT_MEDIA', '/Igenerated/video-x86'
    $outputName = 'void-x86-media'
}
if ($Renderer) {
    $hostBase = '0x50000000'
    & python tools/lift_renderer.py
    if ($LASTEXITCODE) { throw 'Renderer lifting failed' }
    $sources = @($sources | Where-Object { $_ -ne 'generated/video-x86/recomp_dispatch.c' })
    $sources += 'generated/renderer-x86/recomp_dispatch.c'
    $rendererReport = Get-Content -LiteralPath 'generated/renderer-x86/report.json' -Raw | ConvertFrom-Json
    foreach ($source in $rendererReport.sources) { $sources += "generated/renderer-x86/$source" }
    $extraCompilerArguments += '/DVOID_LIFT_RENDERER', '/Igenerated/renderer-x86'
    $outputName = 'void-x86-renderer'
}
if ($NxCharacter) {
    & python tools/lift_nxcharacter.py
    if ($LASTEXITCODE) { throw 'NxCharacter lifting failed' }
    $sources = @($sources | Where-Object { $_ -ne 'generated/renderer-x86/recomp_dispatch.c' })
    $sources += 'generated/nxcharacter-x86/recomp_dispatch.c'
    $characterReport = Get-Content -LiteralPath 'generated/nxcharacter-x86/report.json' -Raw | ConvertFrom-Json
    foreach ($source in $characterReport.sources) { $sources += "generated/nxcharacter-x86/$source" }
    $extraCompilerArguments += '/DVOID_LIFT_NXCHARACTER', '/Igenerated/nxcharacter-x86'
    $outputName = 'void-x86-nxcharacter'
}
$sources | ForEach-Object { '"' + $_ + '"' } | Set-Content -LiteralPath build/x86/sources.rsp -Encoding ASCII
& $compiler /nologo /O2 /W0 /std:c11 /MP4 /DRECOMP_TRACE /D_CRT_SECURE_NO_WARNINGS /Inative /Ireference/pcrecomp/runtime/recomp32 /Ireference/pcrecomp/runtime/native32 /Igenerated/game-x86 @extraCompilerArguments '@build/x86/sources.rsp' /Fobuild/x86/ "/Febuild/x86/$outputName.exe" /link /MACHINE:X86 "/BASE:$hostBase" /DYNAMICBASE:NO /STACK:262144 /MANIFEST:EMBED /MANIFESTUAC:NO /DEBUG "/PDB:build/x86/$outputName.pdb" *> build/x86/compile.log
if ($LASTEXITCODE) { Get-Content -LiteralPath build/x86/compile.log -Tail 30; throw 'x86 host compilation failed' }
Write-Output "Built build/x86/$outputName.exe"
