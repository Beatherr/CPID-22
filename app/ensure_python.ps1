param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPathOutput
)

$ErrorActionPreference = 'Stop'
$installerId = 'Python.Python.3.14'

function Invoke-PythonProbe {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    try {
        $result = & $Executable @Arguments 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $result
        }
    }
    catch {
        return $null
    }

    return $null
}

function Python314YolunuBul {
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        $result = Invoke-PythonProbe -Executable $pythonLauncher.Source -Arguments @(
            '-3.14', '-c', 'import sys; print(sys.executable)'
        )
        if ($result) {
            $path = [string]($result | Select-Object -Last 1)
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($path)
            }
        }
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $result = Invoke-PythonProbe -Executable $pythonCommand.Source -Arguments @(
            '-c', 'import sys; print(sys.version_info[:2] == (3, 14)); print(sys.executable)'
        )
        if ($result -and $result.Count -ge 2 -and $result[0] -eq 'True') {
            $path = [string]$result[-1]
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($path)
            }
        }
    }
    return $null
}

function KullaniciYolunaEkle([string]$Directory) {
    $expanded = [Environment]::ExpandEnvironmentVariables($Directory)
    if (-not (Test-Path -LiteralPath $expanded -PathType Container)) {
        return
    }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @()
    if ($userPath) {
        $entries = @($userPath -split ';' | Where-Object { $_.Trim() })
    }
    $exists = $false
    foreach ($entry in $entries) {
        $resolved = [Environment]::ExpandEnvironmentVariables($entry.Trim().Trim('"'))
        if ([string]::Equals(
                [System.IO.Path]::GetFullPath($resolved).TrimEnd('\'),
                [System.IO.Path]::GetFullPath($expanded).TrimEnd('\'),
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            $exists = $true
            break
        }
    }
    if (-not $exists) {
        $entries += $Directory
        [Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
    }
    if (($env:Path -split ';') -notcontains $expanded) {
        $env:Path = "$expanded;$env:Path"
    }
}

$pythonPath = Python314YolunuBul
if (-not $pythonPath) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python 3.14 yüklü değil ve winget kullanılamıyor. python.org üzerinden Python 3.14 kurup setup.bat dosyasını yeniden çalıştırın.'
    }

    Write-Output 'Python 3.14 bulunamadı. Python Yazılım Vakfı tarafından yayımlanan resmi paket kuruluyor...'
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $winget.Source install `
            --id $installerId `
            --exact `
            --scope user `
            --silent `
            --accept-source-agreements `
            --accept-package-agreements `
            --override '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0'
        $installerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($installerExitCode -ne 0) {
        throw "Resmi Python 3.14 kurulumu başarısız oldu. Çıkış kodu: $installerExitCode."
    }

    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$userPath;$machinePath;$env:Path"
    $pythonPath = Python314YolunuBul
}

if (-not $pythonPath) {
    $candidateDirectories = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314'),
        (Join-Path $env:LOCALAPPDATA 'Python\pythoncore-3.14-64'),
        (Join-Path $env:LOCALAPPDATA 'Python\pythoncore-3.14-32')
    )
    foreach ($directory in $candidateDirectories) {
        $candidate = Join-Path $directory 'python.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $result = Invoke-PythonProbe -Executable $candidate -Arguments @(
                '-c', 'import sys; print(sys.version_info[:2] == (3, 14))'
            )
            if ($result -eq 'True') {
                $pythonPath = [System.IO.Path]::GetFullPath($candidate)
                break
            }
        }
    }
}

if (-not $pythonPath) {
    throw 'Python kurulumu tamamlandı ancak Python 3.14 bulunamadı. Windows''u yeniden başlatıp setup.bat dosyasını tekrar çalıştırın.'
}

$pythonDirectory = Split-Path -Parent $pythonPath
KullaniciYolunaEkle $pythonDirectory
KullaniciYolunaEkle (Join-Path $pythonDirectory 'Scripts')
$version = Invoke-PythonProbe -Executable $pythonPath -Arguments @(
    '-c', "import sys; print('.'.join(map(str, sys.version_info[:3])))"
)
if (-not $version) {
    throw 'Python 3.14 bulundu ancak başlatılamadı.'
}

$output = [System.IO.Path]::GetFullPath($PythonPathOutput)
$outputDirectory = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}
[System.IO.File]::WriteAllText($output, $pythonPath, [System.Text.Encoding]::ASCII)
Write-Output "Python $version kullanılacak: $pythonPath"
Write-Output 'Python 3.14 ve Scripts klasörü bu Windows kullanıcısının PATH değişkenine eklendi.'
