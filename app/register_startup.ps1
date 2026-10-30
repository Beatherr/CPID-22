param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = 'Stop'
$launcher = [System.IO.Path]::GetFullPath($LauncherPath)
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Başlatıcı bulunamadı: $launcher"
}

$startupTask = Get-ScheduledTask -TaskName 'PCActivityMonitor' -ErrorAction SilentlyContinue
if ($null -ne $startupTask) {
    Unregister-ScheduledTask -InputObject $startupTask -Confirm:$false -ErrorAction Stop
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute (Join-Path $env:SystemRoot 'System32\wscript.exe') `
    -Argument ('//B //NoLogo "' + $launcher + '"') `
    -WorkingDirectory (Split-Path -Parent $launcher)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$trigger.Delay = 'PT40S'
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName 'PCActivityMonitor' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

$registeredTask = Get-ScheduledTask -TaskName 'PCActivityMonitor' -ErrorAction Stop
if ($registeredTask.State -eq 'Disabled') {
    Enable-ScheduledTask -TaskName 'PCActivityMonitor' | Out-Null
}

$startupFolder = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$null = New-Item -ItemType Directory -Path $startupFolder -Force
foreach ($legacyShortcut in @('PCActivityMonitor.vbs')) {
    $path = Join-Path $startupFolder $legacyShortcut
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}

$legacyShortcutPath = Join-Path $startupFolder 'PCMonitor.lnk'
if (Test-Path -LiteralPath $legacyShortcutPath -PathType Leaf) {
    $shell = New-Object -ComObject WScript.Shell
    $legacyShortcut = $shell.CreateShortcut($legacyShortcutPath)
    $legacyScript = Join-Path (Split-Path -Parent (Split-Path -Parent $launcher)) 'client.py'
    if (
        [System.IO.Path]::GetFullPath($legacyShortcut.Arguments.Trim("'`"")) -ieq
        [System.IO.Path]::GetFullPath($legacyScript)
    ) {
        Remove-Item -LiteralPath $legacyShortcutPath -Force
    }
}

$shortcutPath = Join-Path $startupFolder 'PCActivityMonitor.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$shortcut.Arguments = '//B //NoLogo "' + $launcher + '"'
$shortcut.WorkingDirectory = Split-Path -Parent $launcher
$shortcut.WindowStyle = 7
$shortcut.Save()

if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "Başlangıç kısayolu oluşturulamadı: $shortcutPath"
}

if ($registeredTask.State -eq 'Disabled') {
    throw 'PCActivityMonitor başlangıç görevi devre dışı.'
}

Write-Output "PCActivityMonitor, $identity kullanıcısı için Başlangıç klasörüne ve oturum açma görevine kaydedildi."
