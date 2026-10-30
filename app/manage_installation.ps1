param(
    [Parameter(Mandatory = $true)]
    [string]$AppDirectory,
    [Parameter(Mandatory = $true)]
    [ValidateSet('Stop', 'Remove')]
    [string]$Mode
)

$ErrorActionPreference = 'Stop'
$resolvedAppDirectory = [System.IO.Path]::GetFullPath($AppDirectory)
$currentScripts = @('client.py', 'start_services.py') | ForEach-Object {
    Join-Path $resolvedAppDirectory $_
}
$legacyScripts = @('bot.py', 'client.py', 'start_services.py') | ForEach-Object {
    Join-Path $resolvedAppDirectory $_
}
$legacyParentScripts = @('bot.py', 'client.py', 'start_services.py') | ForEach-Object {
    Join-Path (Split-Path -Parent $resolvedAppDirectory) $_
}
foreach ($script in $currentScripts) {
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
        throw "Gerekli uygulama dosyası bulunamadı: $script"
    }
}
$scripts = $currentScripts + $legacyScripts + $legacyParentScripts

$processes = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
foreach ($process in $processes) {
    $commandLine = $process.CommandLine
    if (-not $commandLine) {
        continue
    }
    $isMonitorProcess = $false
    foreach ($script in $scripts) {
        if ($commandLine.IndexOf($script, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $isMonitorProcess = $true
            break
        }
    }
    if ($isMonitorProcess) {
        try {
            $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner -ErrorAction Stop
        }
        catch {
            if (-not (Get-Process -Id ([int]$process.ProcessId) -ErrorAction SilentlyContinue)) {
                continue
            }
            throw
        }
        if ($owner.ReturnValue -ne 0 -or "$($owner.Domain)\$($owner.User)" -ine $currentUser) {
            continue
        }
        try {
            Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction Stop
            Write-Output "PC etkinlik izleyicisi işlemi durduruldu: $($process.ProcessId)."
        }
        catch {
            if (Get-Process -Id ([int]$process.ProcessId) -ErrorAction SilentlyContinue) {
                throw
            }
        }
    }
}

Start-Sleep -Milliseconds 500
if ($Mode -eq 'Stop') {
    exit 0
}

$startupFolder = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
foreach ($startupFile in @('PCActivityMonitor.lnk', 'PCActivityMonitor.vbs')) {
    $path = Join-Path $startupFolder $startupFile
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}

$startupTask = Get-ScheduledTask -TaskName 'PCActivityMonitor' -ErrorAction SilentlyContinue
if ($null -ne $startupTask) {
    Unregister-ScheduledTask -InputObject $startupTask -Confirm:$false -ErrorAction Stop
}

$stateDirectory = Join-Path $env:APPDATA 'PCActivityMonitor'
$expectedStateDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $env:APPDATA 'PCActivityMonitor')
)
if ($stateDirectory -and $expectedStateDirectory -eq [System.IO.Path]::GetFullPath($stateDirectory)) {
    if (Test-Path -LiteralPath $expectedStateDirectory -PathType Container) {
        $removed = $false
        for ($attempt = 1; $attempt -le 5 -and -not $removed; $attempt++) {
            try {
                Remove-Item -LiteralPath $expectedStateDirectory -Recurse -Force -ErrorAction Stop
                $removed = $true
            }
            catch {
                if ($attempt -eq 5) {
                    throw "İşlemler durdurulduktan sonra uygulama verileri klasörü kaldırılamadı: $($_.Exception.Message)"
                }
                Start-Sleep -Seconds 1
            }
        }
    }
}

Write-Output 'Başlangıç kısayolu, varsa eski zamanlanmış görev, kullanıcı yapılandırması, günlükler ve özel sanal ortam kaldırıldı.'
Write-Output 'Proje kaynak klasörü korundu. Başka uygulamalar kullanabileceğinden genel Python paketleri kaldırılmadı.'
