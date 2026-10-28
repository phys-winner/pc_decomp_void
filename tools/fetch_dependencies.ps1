$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dependencies = Get-Content -LiteralPath (Join-Path $projectRoot 'dependencies.json') -Raw | ConvertFrom-Json
foreach ($dependency in $dependencies.PSObject.Properties.Value) {
    if ($dependency.vendored) {
        # Bundled file provided by a pinned dependency (bcdec within etcpak).
        $vendoredPath = Join-Path $projectRoot $(if ($dependency.directory) { $dependency.directory } else { $dependency.file })
        if (!(Test-Path -LiteralPath $vendoredPath)) { throw "Missing vendored dependency: $vendoredPath" }
        continue
    }
    $dependencyPath = Join-Path $projectRoot $dependency.directory
    if ($dependency.submodule -and !(Test-Path -LiteralPath (Join-Path $dependencyPath '.git'))) {
        & git -C $projectRoot submodule update --init --checkout -- $dependency.directory
        if ($LASTEXITCODE) { throw "Dependency submodule initialization failed: $($dependency.directory)" }
    }
    if (!$dependency.revision) {
        $source = Join-Path $dependencyPath 'malloc.c'
        if (!(Test-Path -LiteralPath $source)) {
            New-Item -ItemType Directory -Force -Path $dependencyPath | Out-Null
            $download = "$source.download"
            Invoke-WebRequest -Uri $dependency.url -OutFile $download
            if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.sha256) {
                throw 'Downloaded dependency hash mismatch'
            }
            Move-Item -LiteralPath $download -Destination $source
        }
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.sha256) {
            throw 'Vendored dependency hash mismatch'
        }
        continue
    }
    if (!(Test-Path -LiteralPath $dependencyPath)) {
        & git clone $dependency.url $dependencyPath
        if ($LASTEXITCODE) { throw 'Dependency clone failed' }
        & git -C $dependencyPath checkout --detach $dependency.revision
        if ($LASTEXITCODE) { throw 'Dependency checkout failed' }
    }
    $revision = & git -C $dependencyPath rev-parse HEAD
    if ($LASTEXITCODE -or $revision -ne $dependency.revision) {
        throw "Unexpected dependency revision at $dependencyPath; expected $($dependency.revision)"
    }
    $changes = & git -C $dependencyPath status --porcelain --untracked-files=no
    if ($LASTEXITCODE -or $changes) { throw "Modified dependency: $dependencyPath" }
}
