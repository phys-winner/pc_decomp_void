param([int]$WaitSeconds = 10, [switch]$SelfTest, [switch]$GameModule, [switch]$Engine, [switch]$Filesystems, [switch]$Sound, [switch]$Media, [switch]$Renderer, [switch]$NxCharacter)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$hostName = if ($NxCharacter) { 'void-x86-nxcharacter.exe' } elseif ($Renderer) { 'void-x86-renderer.exe' } elseif ($Media) { 'void-x86-media.exe' } elseif ($Sound) { 'void-x86-sound.exe' } elseif ($Filesystems) { 'void-x86-filesystems.exe' } elseif ($Engine) { 'void-x86-engine.exe' } elseif ($GameModule) { 'void-x86-gamemodule.exe' } else { 'void-x86.exe' }
$expectedHost = [IO.Path]::GetFullPath((Join-Path $project "build\x86\$hostName"))
$localConfig = Get-Content -LiteralPath (Join-Path $project 'port.json') -Raw | ConvertFrom-Json
$gameRoot = $localConfig.game_directory
if (![IO.Path]::IsPathRooted($gameRoot)) { $gameRoot = Join-Path $project $gameRoot }
$gameRoot = [IO.Path]::GetFullPath($gameRoot)
$expectedConfig = Join-Path $gameRoot 'bin\win32\Config.exe'
$warningText = 'Failed to choose the optimal settings preset for your video card. Minimum settings were selected.'

function Test-SelectedParent($config, $hostProcess) {
    return $hostProcess -and $hostProcess.ProcessId -eq $config.ParentProcessId -and $hostProcess.ExecutablePath -ieq $expectedHost
}

function Select-AllowedAction($windows) {
    $dialogs = @($windows | Where-Object { $_.Top -and $_.Visible -and $_.Class -ceq '#32770' })
    foreach ($dialog in $dialogs) {
        if ($dialog.Title -cne 'config' -and $dialog.Title -cne 'The Void configuration') {
            throw "Unrecognized Config dialog: $($dialog.Title)"
        }
    }
    $warning = @($dialogs | Where-Object { $_.Title -ceq 'config' })
    if ($warning.Count -gt 1) { throw 'Multiple warning dialogs; refusing ambiguous target.' }
    if ($warning.Count -eq 1) {
        $dialog = $warning[0]
        $message = @($windows | Where-Object { $_.Parent -eq $dialog.Handle -and $_.Class -ceq 'Static' -and $_.Title -ceq $warningText })
        if ($message.Count -ne 1) { throw 'Config warning text does not match the authorized warning.' }
        $kind = 'warning'
    } else {
        $settings = @($dialogs | Where-Object { $_.Title -ceq 'The Void configuration' })
        if ($settings.Count -gt 1) { throw 'Multiple configuration dialogs; refusing ambiguous target.' }
        if ($settings.Count -eq 0) { return $null }
        $dialog = $settings[0]
        $kind = 'settings'
    }
    $buttonId = if ($kind -eq 'warning') { 2 } else { 1 }
    $buttons = @($windows | Where-Object {
        $_.Parent -eq $dialog.Handle -and $_.Class -ceq 'Button' -and $_.Title -ceq 'OK' -and
        $_.ControlId -eq $buttonId -and $_.Visible -and $_.Enabled
    })
    if ($buttons.Count -ne 1) { throw 'Expected one enabled OK button with the observed control ID.' }
    return [pscustomobject]@{ Kind=$kind; Dialog=$dialog.Handle; Button=$buttons[0].Handle }
}

if ($SelfTest) {
    $child = [pscustomobject]@{ParentProcessId=10}
    $parent = [pscustomobject]@{ProcessId=10;ExecutablePath=$expectedHost}
    if (!(Test-SelectedParent $child $parent)) { throw 'Selected host path self-check failed.' }
    $otherHosts = @('void-x86.exe', 'void-x86-gamemodule.exe', 'void-x86-engine.exe', 'void-x86-filesystems.exe', 'void-x86-sound.exe', 'void-x86-media.exe', 'void-x86-renderer.exe', 'void-x86-nxcharacter.exe') | Where-Object { $_ -ne $hostName }
    $wrongPaths = @($otherHosts | ForEach-Object { Join-Path $project "build\x86\$_" })
    $wrongPaths += (Join-Path $project 'build\x86\unknown.exe'), (Join-Path $project "tools\$hostName")
    foreach ($wrongPath in $wrongPaths) {
        $parent.ExecutablePath = $wrongPath
        if (Test-SelectedParent $child $parent) { throw "Unexpected parent executable was accepted: $wrongPath" }
    }
    $parent.ExecutablePath = $expectedHost
    $parent.ProcessId = 11
    if (Test-SelectedParent $child $parent) { throw 'Wrong direct parent PID was accepted.' }
    $fixture = @(
        [pscustomobject]@{Handle=10;Parent=0;Top=$true;Visible=$true;Class='#32770';Title='config'},
        [pscustomobject]@{Handle=11;Parent=10;Top=$false;Visible=$true;Enabled=$true;ControlId=2;Class='Button';Title='OK'},
        [pscustomobject]@{Handle=12;Parent=10;Top=$false;Visible=$true;Class='Static';Title=$warningText}
    )
    $action = Select-AllowedAction $fixture
    if ($action.Kind -ne 'warning' -or $action.Button -ne 11) { throw 'Valid warning self-check failed.' }
    $fixture[2].Title = 'Unexpected error'
    $rejected = $false
    try { Select-AllowedAction $fixture | Out-Null } catch { $rejected = $true }
    if (!$rejected) { throw 'Unknown warning was not rejected.' }
    $fixture[0].Title = 'The Void configuration'
    $fixture[1].ControlId = 1
    $action = Select-AllowedAction $fixture
    if ($action.Kind -ne 'settings') { throw 'Settings self-check failed.' }
    $fixture[1].ControlId = 2
    $rejected = $false
    try { Select-AllowedAction $fixture | Out-Null } catch { $rejected = $true }
    if (!$rejected) { throw 'Wrong control ID was not rejected.' }
    $fixture[0].Title = 'Unrelated dialog'
    $rejected = $false
    try { Select-AllowedAction $fixture | Out-Null } catch { $rejected = $true }
    if (!$rejected) { throw 'Unknown dialog was not rejected.' }
    Write-Output "Startup dialog self-check PASS ($hostName): selected parent accepted; other stage/unknown path/wrong parent and unknown warning/dialog/control rejected; no UI mutation."
    return
}

if ($WaitSeconds -lt 1 -or $WaitSeconds -gt 30) { throw 'WaitSeconds must be between 1 and 30.' }
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class VoidStartupDialogs {
    public delegate bool Callback(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, Callback callback, IntPtr data);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr window, StringBuilder value, int length);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassNameW(IntPtr window, StringBuilder value, int length);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr window);
    [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr window);
    [DllImport("user32.dll")] static extern int GetDlgCtrlID(IntPtr window);
    [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr SendMessageTimeoutW(IntPtr window, uint message, UIntPtr wparam, IntPtr lparam, uint flags, uint timeout, out UIntPtr result);
    public sealed class Record { public long Handle; public long Parent; public bool Top; public uint Process; public string Title; public string Class; public bool Visible; public bool Enabled; public int ControlId; }
    static Record Read(IntPtr window, bool top) {
        uint process; GetWindowThreadProcessId(window, out process);
        var title = new StringBuilder(2048); var cls = new StringBuilder(512);
        GetWindowTextW(window, title, title.Capacity); GetClassNameW(window, cls, cls.Capacity);
        return new Record { Handle=window.ToInt64(), Parent=GetParent(window).ToInt64(), Top=top, Process=process,
            Title=title.ToString(), Class=cls.ToString(), Visible=IsWindowVisible(window), Enabled=IsWindowEnabled(window), ControlId=GetDlgCtrlID(window) };
    }
    public static Record[] ForProcess(uint process) {
        var records = new List<Record>();
        EnumWindows((window,data) => { var item=Read(window,true); if(item.Process==process) {
            records.Add(item); EnumChildWindows(window,(child,x)=>{ records.Add(Read(child,false)); return true; },IntPtr.Zero);
        } return true; },IntPtr.Zero);
        return records.ToArray();
    }
    public static bool Click(long handle, uint expectedProcess) {
        uint process; GetWindowThreadProcessId(new IntPtr(handle),out process);
        if(process!=expectedProcess) throw new InvalidOperationException("Button ownership changed.");
        UIntPtr result;
        return SendMessageTimeoutW(new IntPtr(handle),0x00F5,UIntPtr.Zero,IntPtr.Zero,3,2000,out result)!=IntPtr.Zero;
    }
}
'@

$deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
$clicked = @{}
while ([DateTime]::UtcNow -lt $deadline) {
    $configs = @(Get-CimInstance Win32_Process -Filter "Name='config.exe'" | Where-Object { $_.ExecutablePath -ieq $expectedConfig })
    foreach ($config in $configs) {
        $hostProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($config.ParentProcessId)"
        if (!(Test-SelectedParent $config $hostProcess)) { continue }
        $windows = [VoidStartupDialogs]::ForProcess($config.ProcessId)
        $action = Select-AllowedAction $windows
        if (!$action) { continue }
        $token = "$($config.ProcessId):$($config.CreationDate):$($action.Dialog):$($action.Kind)"
        if ($clicked.ContainsKey($token)) { continue }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($config.ProcessId)"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($config.ParentProcessId)"
        if (!$current -or $current.ExecutablePath -ine $expectedConfig -or $current.CreationDate -ne $config.CreationDate -or
            $current.ParentProcessId -ne $config.ParentProcessId -or !(Test-SelectedParent $current $parent)) {
            throw 'Config/host identity changed before click; refusing action.'
        }
        $fresh = Select-AllowedAction ([VoidStartupDialogs]::ForProcess($config.ProcessId))
        if (!$fresh -or $fresh.Button -ne $action.Button -or $fresh.Dialog -ne $action.Dialog) { throw 'Dialog changed before click; refusing action.' }
        if (![VoidStartupDialogs]::Click($action.Button, $config.ProcessId)) { throw 'Authorized IDOK click timed out.' }
        $clicked[$token] = $true
        Write-Output "Accepted $($action.Kind) OK: Config PID=$($config.ProcessId), host PID=$($config.ParentProcessId), HWND=$($action.Dialog). Current controls were not edited."
    }
    if ($clicked.Count -gt 0 -and $configs.Count -eq 0) { break }
    Start-Sleep -Milliseconds 200
}
if ($clicked.Count -eq 0) { Write-Output 'No authorized startup dialogs found; no UI action performed.' }
else { Write-Output "Accepted dialogs: $($clicked.Count)." }
