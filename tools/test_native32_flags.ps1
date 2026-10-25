param([switch]$Project)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$outputName = if ($Project) { 'native32-flags-project' } else { 'native32-flags' }
$outputDirectory = Join-Path $projectRoot "build\$outputName"
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$vsRoot = & (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe") -latest -products '*' -property installationPath
if (!$vsRoot) { throw 'Visual Studio with the x86 C++ toolchain is required' }
$msvc = Get-ChildItem -LiteralPath (Join-Path $vsRoot 'VC\Tools\MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$sdkRoot = (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10")
$sdkVersion = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'Lib') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$env:INCLUDE = "$($msvc.FullName)\include;$sdkRoot\Include\$($sdkVersion.Name)\ucrt;$sdkRoot\Include\$($sdkVersion.Name)\shared;$sdkRoot\Include\$($sdkVersion.Name)\um"
$env:LIB = "$($msvc.FullName)\lib\x86;$sdkRoot\Lib\$($sdkVersion.Name)\ucrt\x86;$sdkRoot\Lib\$($sdkVersion.Name)\um\x86"
$env:PATH = "$($msvc.FullName)\bin\Hostx64\x86;$env:PATH"
$compiler = Join-Path $msvc.FullName 'bin\Hostx64\x86\cl.exe'
$sources = @('tests/native32_flags_probe.c', 'reference/pcrecomp/runtime/native32/native32.c',
             'reference/pcrecomp/runtime/recomp32/image_loader.c', 'reference/pcrecomp/runtime/recomp32/recomp_trace.c')
$trackedRuntimeFiles = @($sources | Where-Object { $_ -like 'reference/*' }) + @('reference/pcrecomp/runtime/recomp32/recomp_types.h')
$projectCompilerArguments = @()
if ($Project) {
    $sources[1] = 'native/void_runtime.c'
    $projectCompilerArguments = @('/Inative')
}
$before = @($trackedRuntimeFiles | ForEach-Object { Get-FileHash -LiteralPath $_ -Algorithm SHA256 })
& $compiler /nologo /O2 /W3 /std:c11 /D_CRT_SECURE_NO_WARNINGS @projectCompilerArguments /Ireference/pcrecomp/runtime/recomp32 /Ireference/pcrecomp/runtime/native32 @sources "/Fo$outputDirectory\" "/Fe$outputDirectory\native32-flags.exe" /link /MACHINE:X86 /NXCOMPAT *> "$outputDirectory\compile.log"
if ($LASTEXITCODE) { Get-Content -LiteralPath "$outputDirectory\compile.log" -Tail 30; throw 'Standalone native32 flags probe compilation failed' }
$probeOutput = @(& "$outputDirectory\native32-flags.exe" 2>&1)
$probeExitCode = $LASTEXITCODE
$probeOutput | Set-Content -LiteralPath "$outputDirectory\result.txt" -Encoding utf8
$probeOutput | Write-Output
$after = @($trackedRuntimeFiles | ForEach-Object { Get-FileHash -LiteralPath $_ -Algorithm SHA256 })
for ($i = 0; $i -lt $before.Count; $i++) {
    if ($before[$i].Hash -ne $after[$i].Hash) { throw "Runtime file changed during probe: $($before[$i].Path)" }
}
[ordered]@{
    utc = [DateTime]::UtcNow.ToString('o')
    test_exit_code = $probeExitCode
    runtime_commit = (& git -C reference/pcrecomp rev-parse HEAD)
    compiler_toolset = $msvc.Name
    sdk = $sdkVersion.Name
    project_overlay = [bool]$Project
    project_overlay_sha256 = $(if ($Project) { (Get-FileHash -LiteralPath native/recomp_types.h -Algorithm SHA256).Hash } else { $null })
    sources = @($before | Select-Object Path,Hash)
    runtime_sources_unchanged = $true
    no_guest_pe_or_game_dll_load = $true
    output = $probeOutput
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$outputDirectory\result.json" -Encoding utf8
# Exit 1 means context restoration failed; do not relabel a reproduced defect as PASS.
exit $probeExitCode
