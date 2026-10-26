param(
    [string]$Sdk = "$env:LOCALAPPDATA\Android\Sdk",
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$NativeLibrary = '',
    [string]$Serial = '',
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$build = Join-Path $project 'build\android'
$tools = Join-Path $Sdk 'build-tools\36.1.0'
$androidJar = Join-Path $Sdk 'platforms\android-36\android.jar'
$javac = Join-Path $JavaHome 'bin\javac.exe'
$java = Join-Path $JavaHome 'bin\java.exe'
$keytool = Join-Path $JavaHome 'bin\keytool.exe'
foreach ($path in @($androidJar, $javac, $java, $keytool, "$tools\aapt2.exe", "$tools\d8.bat", "$tools\zipalign.exe", "$tools\apksigner.bat")) {
    if (!(Test-Path -LiteralPath $path)) { throw "Required build tool missing: $path" }
}
if ($Install -and !$Serial) { throw 'Install requires an explicit -Serial.' }
if ($NativeLibrary -and !(Test-Path -LiteralPath $NativeLibrary -PathType Leaf)) { throw "Native library missing: $NativeLibrary" }
$signerJson = & python (Join-Path $PSScriptRoot 'debug_signer.py') --project $project --keytool $keytool
if ($LASTEXITCODE -ne 0) { throw 'Protected project debug signer validation failed; no key was changed.' }
$signer = $signerJson | ConvertFrom-Json
$keystore = $signer.keystore
Write-Output "Debug signer certificate SHA-256: $($signer.certificate_sha256)"
foreach ($directory in @($build, "$build\classes", "$build\dex", "$build\testclasses", "$build\generated")) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
foreach ($directory in @("$build\classes", "$build\dex", "$build\testclasses", "$build\generated")) {
    Get-ChildItem -LiteralPath $directory -File -Recurse | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
}
function Run([string]$program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "$program failed with exit code $LASTEXITCODE" }
}
$core = Join-Path $project 'android\src\org\thevoid\portprobe\TouchInput.java'
Run $javac @('--release', '8', '-d', "$build\testclasses", $core, "$project\tests\TouchInputTest.java")
Run $java @('-ea', '-cp', "$build\testclasses", 'org.thevoid.portprobe.TouchInputTest')
Run "$tools\aapt2.exe" @('link', '-I', $androidJar, '--manifest', "$project\android\AndroidManifest.xml", '--java', "$build\generated", '-o', "$build\base.apk")
$sources = @(Get-ChildItem -LiteralPath "$project\android\src" -Filter '*.java' -Recurse | ForEach-Object FullName)
Run $javac (@('--release', '8', '-cp', $androidJar, '-d', "$build\classes") + $sources)
$classes = @(Get-ChildItem -LiteralPath "$build\classes" -Filter '*.class' -Recurse | ForEach-Object FullName)
Run "$tools\d8.bat" (@('--lib', $androidJar, '--min-api', '26', '--output', "$build\dex") + $classes)
Copy-Item -LiteralPath "$build\base.apk" -Destination "$build\unsigned.apk" -Force
Add-Type -AssemblyName System.IO.Compression
$archive = [System.IO.Compression.ZipFile]::Open("$build\unsigned.apk", [System.IO.Compression.ZipArchiveMode]::Update)
try {
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, "$build\dex\classes.dex", 'classes.dex', [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    if ($NativeLibrary) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, (Resolve-Path -LiteralPath $NativeLibrary).Path, 'lib/arm64-v8a/libvoidprobe.so', [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $archive.Dispose() }
Run "$tools\zipalign.exe" @('-f', '-p', '4', "$build\unsigned.apk", "$build\aligned.apk")
$apk = "$build\the-void-input-test.apk"
Run "$tools\apksigner.bat" @('sign', '--ks', $keystore, '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--out', $apk, "$build\aligned.apk")
Run "$tools\apksigner.bat" @('verify', '--verbose', $apk)
if ($Install) {
    Run "$Sdk\platform-tools\adb.exe" @('-s', $Serial, 'install', '-r', $apk)
    Run "$Sdk\platform-tools\adb.exe" @('-s', $Serial, 'shell', 'am', 'start', '-W', '-n', 'org.thevoid.portprobe/.MainActivity')
}
Write-Output "APK: $apk"
