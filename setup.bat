@echo off
setlocal
chcp 65001 >nul
title Personal PC Control Panel Setup

cd /d "%~dp0"
set "APP_DIR=%~dp0app"
set "MANAGE_SCRIPT=%APP_DIR%\manage_installation.ps1"
set "PYTHON_PATH_FILE=%TEMP%\PCActivityMonitor-python-%RANDOM%.txt"

if not exist "%MANAGE_SCRIPT%" (
    echo [ERROR] app\manage_installation.ps1 was not found.
    pause
    exit /b 1
)

echo ============================================================
echo          PERSONAL PC CONTROL PANEL - SETUP
echo ============================================================
echo [1] Install or reconfigure
echo [2] Remove this user's installation and local data
echo [3] Restart the PC control panel
echo [Q] Quit
echo.
choice /c 123Q /n /m "Choose 1, 2, 3, or Q: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto :restart
if errorlevel 2 goto :remove
if errorlevel 1 goto :install

:remove
echo.
echo This stops the control panel, removes its Windows Startup shortcut,
echo and deletes its configuration, logs, and private Python environment.
echo.
choice /c YN /n /m "Continue with removal? [Y/N] "
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%MANAGE_SCRIPT%" -AppDirectory "%APP_DIR%" -Mode Remove
if errorlevel 1 (
    echo [ERROR] Removal did not finish. See the error above.
    pause
    exit /b 1
)
echo.
echo [SUCCESS] This Windows user's PC control panel was removed.
echo The project source files remain in this folder so you can install again later.
echo Global Python packages from older installations are left untouched.
pause
exit /b 0

:restart
set "STATE_DIR=%APPDATA%\PCActivityMonitor"
set "VENV_PYTHON=%STATE_DIR%\venv\Scripts\python.exe"
if not exist "%MANAGE_SCRIPT%" (
    echo [ERROR] app\manage_installation.ps1 was not found.
    goto :error
)
if not exist "%APP_DIR%\start_services.py" (
    echo [ERROR] app\start_services.py was not found.
    goto :error
)
if not exist "%STATE_DIR%\config.json" (
    echo [ERROR] No saved installation was found. Choose 1 to install or reconfigure first.
    goto :error
)
if not exist "%VENV_PYTHON%" (
    echo [ERROR] The private Python environment was not found. Choose 1 to reinstall.
    goto :error
)

echo.
echo Stopping the current PC control panel...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%MANAGE_SCRIPT%" -AppDirectory "%APP_DIR%" -Mode Stop
if errorlevel 1 (
    echo [ERROR] Could not safely stop the PC control panel.
    goto :error
)

echo.
echo Starting the PC control panel and waiting for it to become ready...
"%VENV_PYTHON%" "%APP_DIR%\start_services.py" --wait
if errorlevel 1 (
    echo.
    echo [ERROR] The PC control panel did not become ready after restarting.
    echo Log folder: "%STATE_DIR%"
    echo The latest startup, client, and Discord log lines are displayed above.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] The PC control panel restarted successfully.
echo Logs: "%STATE_DIR%"
exit /b 0

:install
if not exist "%APP_DIR%\client.py" (
    echo [ERROR] app\client.py was not found.
    goto :error
)
if not exist "%APP_DIR%\discord_control.py" (
    echo [ERROR] app\discord_control.py was not found.
    goto :error
)
if not exist "%APP_DIR%\start_hidden.vbs" (
    echo [ERROR] app\start_hidden.vbs was not found.
    goto :error
)
if not exist "%APP_DIR%\setup_config.py" (
    echo [ERROR] app\setup_config.py was not found.
    goto :error
)
if not exist "%APP_DIR%\start_services.py" (
    echo [ERROR] app\start_services.py was not found.
    goto :error
)
if not exist "%APP_DIR%\register_startup.ps1" (
    echo [ERROR] app\register_startup.ps1 was not found.
    goto :error
)
if not exist "%APP_DIR%\ensure_python.ps1" (
    echo [ERROR] app\ensure_python.ps1 was not found.
    goto :error
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\ensure_python.ps1" -PythonPathOutput "%PYTHON_PATH_FILE%"
if errorlevel 1 (
    echo [ERROR] Could not locate or install Python 3.14.
    goto :error
)
if not exist "%PYTHON_PATH_FILE%" (
    echo [ERROR] Python installer did not provide a Python executable path.
    goto :error
)
set /p "PYTHON_EXE="<"%PYTHON_PATH_FILE%"
del "%PYTHON_PATH_FILE%" >nul 2>&1
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python executable was not found: "%PYTHON_EXE%"
    goto :error
)

echo.
echo [1/5] Collecting settings and showing the privacy notice...
echo Setup will not save or start the control panel unless the PC user confirms.
set "SETUP_CONFIG_ARGS="
if not exist "%APPDATA%\PCActivityMonitor\config.json" goto :collect_settings
echo.
echo A previous PC control panel configuration was found.
choice /c 12 /n /m "[1] Continue with saved token and IDs  [2] Enter new settings: "
if errorlevel 2 goto :enter_new_settings
set "SETUP_CONFIG_ARGS=--reuse-existing"
goto :collect_settings

:enter_new_settings
set "SETUP_CONFIG_ARGS="

:collect_settings
"%PYTHON_EXE%" "%APP_DIR%\setup_config.py" %SETUP_CONFIG_ARGS%
if errorlevel 1 (
    echo.
    echo Setup was cancelled or the configuration could not be saved.
    exit /b 1
)

echo.
echo [2/5] Stopping this installation before applying the reviewed settings...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%MANAGE_SCRIPT%" -AppDirectory "%APP_DIR%" -Mode Stop
if errorlevel 1 (
    echo [ERROR] Could not safely stop the previous panel processes.
    goto :error
)

set "STATE_DIR=%APPDATA%\PCActivityMonitor"
set "VENV_DIR=%STATE_DIR%\venv"
echo.
echo [3/5] Removing the previous environment and old activity logs...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$state = Join-Path $env:APPDATA 'PCActivityMonitor'; $venv = Join-Path $state 'venv'; if (Test-Path -LiteralPath $venv) { Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction Stop }; foreach ($name in @('bot.log', 'client.log', 'discord.log', 'startup.log', 'startup_launcher.log', 'status_message.json')) { $path = Join-Path $state $name; if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force -ErrorAction Stop } }"
if errorlevel 1 (
    echo [ERROR] Could not safely clear the old local environment and logs.
    goto :error
)
echo.
echo Creating a new private Python environment and installing dependencies...
"%PYTHON_EXE%" -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Could not create the private Python environment.
    goto :error
)
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Could not prepare pip in the private Python environment.
    goto :error
)
"%VENV_DIR%\Scripts\python.exe" -m pip install discord.py psutil pystray Pillow
if errorlevel 1 (
    echo [ERROR] Package installation failed.
    goto :error
)
"%VENV_DIR%\Scripts\python.exe" "%APP_DIR%\setup_config.py" --set-pythonw-path "%VENV_DIR%\Scripts\pythonw.exe"
if errorlevel 1 (
    echo [ERROR] Could not save the private Python runtime path.
    goto :error
)

echo.
echo [4/5] Registering automatic startup for this Windows user...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\register_startup.ps1" -LauncherPath "%APP_DIR%\start_hidden.vbs"
if errorlevel 1 (
    echo [ERROR] Could not add the panel to this user's Startup folder.
    goto :error
)

echo.
echo [5/5] Starting the PC control panel...
"%VENV_DIR%\Scripts\python.exe" "%APP_DIR%\start_services.py" --wait
if errorlevel 1 (
    echo.
    echo [ERROR] The PC control panel did not become ready.
    echo Log folder: "%APPDATA%\PCActivityMonitor"
    echo The latest startup, client, and Discord log lines are displayed above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [SUCCESS] Setup completed.
echo ============================================================
echo The Discord control panel is running in the background.
echo Open your private Discord control channel to use the Embed buttons.
echo Logs: "%APPDATA%\PCActivityMonitor"
echo Run setup.bat again to reconfigure or remove this installation.
echo You can close this setup window.
exit /b 0

:error
echo.
echo Setup did not complete. Fix the error above and run setup.bat again.
pause
exit /b 1
