param([switch]$GameModule, [switch]$Engine, [switch]$Filesystems, [switch]$Sound, [switch]$Media, [switch]$Renderer, [switch]$NxCharacter)
$ErrorActionPreference = 'Stop'
if ($NxCharacter) { $Renderer = $true }
if ($Renderer) { $Media = $true }
if ($Media) { $Sound = $true }
if ($Sound) { $Filesystems = $true }
if ($Filesystems) { $Engine = $true }
if ($Engine) { $GameModule = $true }
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'port.json') -Raw | ConvertFrom-Json
$gameBin = Join-Path $config.game_directory 'bin\win32'
$originalHash = (Get-FileHash -LiteralPath (Join-Path $gameBin 'Game.exe') -Algorithm SHA256).Hash
if ($originalHash -ine $config.game_exe.original_sha256) { throw 'Original Game.exe changed; regenerate and validate addresses.' }
$report = Get-Content -LiteralPath (Join-Path $projectRoot 'generated\game-x86\report.json') -Raw | ConvertFrom-Json
$recovered = Join-Path $projectRoot 'generated\input\Game.exe'
if ((Get-FileHash -LiteralPath $recovered -Algorithm SHA256).Hash -ine $report.binary_sha256) { throw 'Recovered Game.exe hash mismatch.' }
$outputName = 'void-x86'
if ($GameModule) {
    $outputName = 'void-x86-gamemodule'
    $moduleReport = Get-Content -LiteralPath (Join-Path $projectRoot 'generated\gamemodule-x86\report.json') -Raw | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath (Join-Path $gameBin 'GameModule.dll') -Algorithm SHA256).Hash -ine $moduleReport.binary_sha256) { throw 'GameModule.dll changed; regenerate and validate addresses.' }
}
$extraArguments = @()
if ($Engine) {
    $outputName = 'void-x86-engine'
    $engineReport = Get-Content -LiteralPath (Join-Path $projectRoot 'generated\engine-x86\report.json') -Raw | ConvertFrom-Json
    $engineImage = Join-Path $projectRoot 'generated\input\Engine.dll'
    if ((Get-FileHash -LiteralPath (Join-Path $gameBin 'Engine.dll') -Algorithm SHA256).Hash -ine $engineReport.binary_sha256) { throw 'Original Engine.dll changed.' }
    if ((Get-FileHash -LiteralPath $engineImage -Algorithm SHA256).Hash -ine $engineReport.rebased_sha256) { throw 'Private Engine.dll hash mismatch.' }
    $extraArguments = @('--engine-image', $engineImage)
}
if ($Filesystems) {
    $outputName = 'void-x86-filesystems'
    foreach ($module in @('FS','VFS')) {
        $fileReport = Get-Content -LiteralPath (Join-Path $projectRoot "generated\$($module.ToLower())-x86\report.json") -Raw | ConvertFrom-Json
        $fileImage = Join-Path $projectRoot "generated\input\$module.dll"
        if ((Get-FileHash -LiteralPath (Join-Path $gameBin "$module.dll") -Algorithm SHA256).Hash -ine $fileReport.binary_sha256) { throw "Original $module.dll changed." }
        if ((Get-FileHash -LiteralPath $fileImage -Algorithm SHA256).Hash -ine $fileReport.rebased_sha256) { throw "Private $module.dll hash mismatch." }
        $extraArguments += "--$($module.ToLower())-image", $fileImage
    }
}
if ($Sound) {
    $outputName = 'void-x86-sound'
    foreach ($module in @('Sound')) {
        $mediaReport = Get-Content -LiteralPath (Join-Path $projectRoot "generated\$($module.ToLower())-x86\report.json") -Raw | ConvertFrom-Json
        $mediaImage = Join-Path $projectRoot "generated\input\$module.dll"
        if ((Get-FileHash -LiteralPath (Join-Path $gameBin "$module.dll") -Algorithm SHA256).Hash -ine $mediaReport.binary_sha256) { throw "Original $module.dll changed." }
        if ((Get-FileHash -LiteralPath $mediaImage -Algorithm SHA256).Hash -ine $mediaReport.rebased_sha256) { throw "Private $module.dll hash mismatch." }
        $extraArguments += "--$($module.ToLower())-image", $mediaImage
    }
}
if ($Media) {
    $outputName = 'void-x86-media'
    $videoReport = Get-Content -LiteralPath (Join-Path $projectRoot 'generated/video-x86/report.json') -Raw | ConvertFrom-Json
    $videoImage = Join-Path $projectRoot 'generated/input/Video.dll'
    if ((Get-FileHash -LiteralPath (Join-Path $gameBin 'Video.dll') -Algorithm SHA256).Hash -ine $videoReport.binary_sha256) { throw 'Original Video.dll changed.' }
    if ((Get-FileHash -LiteralPath $videoImage -Algorithm SHA256).Hash -ine $videoReport.rebased_sha256) { throw 'Private Video.dll hash mismatch.' }
    $extraArguments += '--video-image', $videoImage
}
foreach ($stage in @(@{Enabled=$Renderer;Module='RendererD3D';Generated='renderer';Output='renderer'},
                     @{Enabled=$NxCharacter;Module='NxCharacter';Generated='nxcharacter';Output='nxcharacter'})) {
    if (!$stage.Enabled) { continue }
    $outputName = "void-x86-$($stage.Output)"
    $stageReport = Get-Content -LiteralPath (Join-Path $projectRoot "generated\$($stage.Generated)-x86\report.json") -Raw | ConvertFrom-Json
    $stageImage = Join-Path $projectRoot "generated\input\$($stage.Module).dll"
    if ((Get-FileHash -LiteralPath (Join-Path $gameBin "$($stage.Module).dll") -Algorithm SHA256).Hash -ine $stageReport.binary_sha256) { throw "Original $($stage.Module).dll changed." }
    if ((Get-FileHash -LiteralPath $stageImage -Algorithm SHA256).Hash -ine $stageReport.rebased_sha256) { throw "Private $($stage.Module).dll hash mismatch." }
    $extraArguments += "--$($stage.Generated)-image", $stageImage
}
$profileDirectory = Join-Path $projectRoot 'build\test-profile'
New-Item -ItemType Directory -Force -Path $profileDirectory | Out-Null
$env:VOID_PROFILE_ROOT = $profileDirectory
$executable = Join-Path $projectRoot "build\x86\$outputName.exe"
if (!(Test-Path -LiteralPath $executable -PathType Leaf)) { throw "Build first: $executable" }
Write-Output "Running $outputName with isolated documents at $profileDirectory"
& $executable $recovered $gameBin @extraArguments
exit $LASTEXITCODE
