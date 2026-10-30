param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPathOutput
)

$ErrorActionPreference = 'Stop'
$installerId = 'Python.Python.3.14'

function Get-Python314Path {
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        $result = & $pythonLauncher.Source -3.14 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) {
            $path = [string]($result | Select-Object -Last 1)
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($path)
            }
        }
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $result = & $pythonCommand.Source -c "import sys; print(sys.version_info[:2] == (3, 14)); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $result.Count -ge 2 -and $result[0] -eq 'True') {
            $path = [string]$result[-1]
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($path)
            }
        }
    }
    return $null
}

function Add-CurrentUserPath([string]$Directory) {
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

$pythonPath = Get-Python314Path
if (-not $pythonPath) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python 3.14 is not installed and winget is unavailable. Install Python 3.14 from python.org, then rerun setup.bat.'
    }

    Write-Output 'Python 3.14 was not found. Installing the official Python Software Foundation package...'
    & $winget.Source install `
        --id $installerId `
        --exact `
        --scope user `
        --silent `
        --accept-source-agreements `
        --accept-package-agreements `
        --override '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0'
    if ($LASTEXITCODE -ne 0) {
        throw "The official Python 3.14 installation failed with exit code $LASTEXITCODE."
    }

    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$userPath;$machinePath;$env:Path"
    $pythonPath = Get-Python314Path
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
            $result = & $candidate -c "import sys; print(sys.version_info[:2] == (3, 14))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $result -eq 'True') {
                $pythonPath = [System.IO.Path]::GetFullPath($candidate)
                break
            }
        }
    }
}

if (-not $pythonPath) {
    throw 'Python installation finished, but Python 3.14 could not be located. Restart Windows and rerun setup.bat.'
}

$pythonDirectory = Split-Path -Parent $pythonPath
Add-CurrentUserPath $pythonDirectory
Add-CurrentUserPath (Join-Path $pythonDirectory 'Scripts')
$version = & $pythonPath -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.14 was found but could not be started.'
}

$output = [System.IO.Path]::GetFullPath($PythonPathOutput)
$outputDirectory = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}
[System.IO.File]::WriteAllText($output, $pythonPath, [System.Text.Encoding]::ASCII)
Write-Output "Using Python $version at $pythonPath"
Write-Output 'Python 3.14 and its Scripts directory are available on this Windows user PATH.'
