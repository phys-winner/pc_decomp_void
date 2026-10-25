param(
    [Parameter(Mandatory=$true)][string]$GameDirectory
)
$ErrorActionPreference = 'Stop'
if ([IntPtr]::Size -ne 4) { throw 'Run this dependency probe in 32-bit Windows PowerShell (SysWOW64).' }
if (!(Test-Path -LiteralPath "$GameDirectory\Game.exe")) { throw "Original game missing: $GameDirectory" }
Set-Location -LiteralPath $GameDirectory
[Environment]::CurrentDirectory = $GameDirectory
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class VoidDependencyProbe {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr LoadLibraryW(string path);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint GetModuleFileNameW(IntPtr module, StringBuilder name, int size);
    [DllImport("kernel32.dll", CharSet=CharSet.Ansi, SetLastError=true)]
    public static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool FreeLibrary(IntPtr module);
}
'@
$names = @('PhysXLoader.dll', 'NxCharacter.dll', 'Engine.dll', 'RendererD3D.dll', 'Sound.dll', 'Video.dll', 'FS.dll', 'VFS.dll', 'GameModule.dll', 'd3dx9_36.dll')
foreach ($name in $names) {
    $module = [VoidDependencyProbe]::LoadLibraryW($name)
    $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    if ($module -eq [IntPtr]::Zero) {
        Write-Output "$name : FAIL Win32=$errorCode"
        continue
    }
    try {
        $resolved = New-Object Text.StringBuilder 32768
        [VoidDependencyProbe]::GetModuleFileNameW($module, $resolved, $resolved.Capacity) | Out-Null
        Write-Output "$name : PASS $resolved"
        if ($name -eq 'PhysXLoader.dll') {
            $factory = [VoidDependencyProbe]::GetProcAddress($module, 'NxCreatePhysicsSDK')
            if ($factory -eq [IntPtr]::Zero) { throw 'PhysXLoader is missing NxCreatePhysicsSDK.' }
            Write-Output 'NxCreatePhysicsSDK : PASS export present (SDK creation not invoked)'
        }
    } finally { [VoidDependencyProbe]::FreeLibrary($module) | Out-Null }
}
