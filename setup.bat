@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
title Kişisel Bilgisayar Kontrol Paneli Kurulumu

cd /d "%~dp0"
set "APP_DIR=%~dp0app"
set "MANAGE_SCRIPT=%APP_DIR%\manage_installation.ps1"
set "PYTHON_PATH_FILE=%TEMP%\PCActivityMonitor-python-%RANDOM%.txt"

if not exist "%MANAGE_SCRIPT%" (
    echo [HATA] app\manage_installation.ps1 bulunamadı.
    pause
    exit /b 1
)

echo ============================================================
echo          KİŞİSEL BİLGİSAYAR KONTROLÜ - KURULUM
echo ============================================================
echo [1] Kur veya yeniden yapılandır
echo [2] Bu kullanıcının kurulumunu ve yerel verileri kaldır
echo [3] Bilgisayar kontrol panelini yeniden başlat
echo [Q] Çıkış
echo.
choice /c 123Q /n /m "1, 2, 3 veya Q seç: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto :restart
if errorlevel 2 goto :remove
if errorlevel 1 goto :install

:remove
echo.
echo Kontrol paneli durdurulur; Windows başlangıç kısayolu,
echo yapılandırması, günlükleri ve özel Python ortamı kaldırılır.
echo.
choice /c EH /n /m "Kaldırma işlemine devam edilsin mi? [E/H] "
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%MANAGE_SCRIPT%" -AppDirectory "%APP_DIR%" -Mode Remove
if errorlevel 1 (
    echo [HATA] Kaldırma tamamlanamadı. Yukarıdaki hatayı inceleyin.
    pause
    exit /b 1
)
echo.
echo [BAŞARILI] Bu Windows kullanıcısının bilgisayar kontrol paneli kaldırıldı.
echo Daha sonra yeniden kurabilmeniz için proje kaynak dosyaları bu klasörde bırakıldı.
echo Önceki kurulumlardan kalan genel Python paketlerine dokunulmadı.
pause
exit /b 0

:restart
set "STATE_DIR=%APPDATA%\PCActivityMonitor"
set "VENV_PYTHON=%STATE_DIR%\venv\Scripts\python.exe"
if not exist "%MANAGE_SCRIPT%" (
    echo [HATA] app\manage_installation.ps1 bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\start_services.py" (
    echo [HATA] app\start_services.py bulunamadı.
    goto :error
)
if not exist "%STATE_DIR%\config.json" (
    echo [HATA] Kayıtlı kurulum bulunamadı. Önce 1 ile kurulum veya yapılandırma yapın.
    goto :error
)
if not exist "%VENV_PYTHON%" (
    echo [HATA] Özel Python ortamı bulunamadı. Yeniden kurmak için 1'i seçin.
    goto :error
)

echo.
echo Kurulum ayarları ve gizlilik onayı denetleniyor...
"%VENV_PYTHON%" "%APP_DIR%\start_services.py" --check-config
if errorlevel 1 (
    echo.
    echo Mevcut servis durdurulmadı. Yukarıdaki adımları tamamlayıp yeniden deneyin.
    goto :error
)

echo.
echo Mevcut bilgisayar kontrol paneli durduruluyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%MANAGE_SCRIPT%" -AppDirectory "%APP_DIR%" -Mode Stop
if errorlevel 1 (
    echo [HATA] Bilgisayar kontrol paneli güvenli biçimde durdurulamadı.
    goto :error
)

echo.
echo Bilgisayar kontrol paneli başlatılıyor ve hazır olması bekleniyor...
"%VENV_PYTHON%" "%APP_DIR%\start_services.py" --wait
if errorlevel 1 (
    echo.
    echo [HATA] Yeniden başlatma sonrası bilgisayar kontrol paneli hazır olmadı.
    echo Günlük klasörü: "%STATE_DIR%"
    echo Başlangıç, istemci ve Discord günlüklerinin son satırları yukarıda gösterildi.
    pause
    exit /b 1
)

echo.
echo [BAŞARILI] Bilgisayar kontrol paneli yeniden başlatıldı.
echo Günlükler: "%STATE_DIR%"
exit /b 0

:install
if not exist "%APP_DIR%\client.py" (
    echo [HATA] app\client.py bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\discord_control.py" (
    echo [HATA] app\discord_control.py bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\start_hidden.vbs" (
    echo [HATA] app\start_hidden.vbs bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\setup_config.py" (
    echo [HATA] app\setup_config.py bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\start_services.py" (
    echo [HATA] app\start_services.py bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\register_startup.ps1" (
    echo [HATA] app\register_startup.ps1 bulunamadı.
    goto :error
)
if not exist "%APP_DIR%\ensure_python.ps1" (
    echo [HATA] app\ensure_python.ps1 bulunamadı.
    goto :error
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\ensure_python.ps1" -PythonPathOutput "%PYTHON_PATH_FILE%"
if errorlevel 1 (
    echo [HATA] Python 3.14 bulunamadı veya kurulamadı.
    goto :error
)
if not exist "%PYTHON_PATH_FILE%" (
    echo [HATA] Python kurucusu Python çalıştırılabilir dosyasının yolunu vermedi.
    goto :error
)
set /p "PYTHON_EXE="<"%PYTHON_PATH_FILE%"
del "%PYTHON_PATH_FILE%" >nul 2>&1
if not exist "%PYTHON_EXE%" (
    echo [HATA] Python çalıştırılabilir dosyası bulunamadı: "%PYTHON_EXE%"
    goto :error
)

echo.
echo [1/5] Ayarlar alınıyor ve gizlilik bildirimi gösteriliyor...
echo Bilgisayar kullanıcısı onaylamadıkça ayarlar kaydedilmez ve panel başlatılmaz.
set "SETUP_CONFIG_ARGS="
if not exist "%APPDATA%\PCActivityMonitor\config.json" goto :collect_settings
echo.
echo Önceki bir bilgisayar kontrol paneli yapılandırması bulundu.
choice /c 12 /n /m "[1] Kayıtlı token ve ID'lerle devam et  [2] Yeni ayarları gir: "
if errorlevel 2 goto :enter_new_settings
set "SETUP_CONFIG_ARGS=--reuse-existing"
goto :collect_settings

:enter_new_settings
set "SETUP_CONFIG_ARGS="

:collect_settings
"%PYTHON_EXE%" "%APP_DIR%\setup_config.py" %SETUP_CONFIG_ARGS%
if errorlevel 1 (
    echo.
    echo Kurulum iptal edildi veya yapılandırma kaydedilemedi.
    exit /b 1
)

echo.
echo [2/5] Onaylanan ayarları uygulamadan önce bu kurulum durduruluyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%MANAGE_SCRIPT%" -AppDirectory "%APP_DIR%" -Mode Stop
if errorlevel 1 (
    echo [HATA] Önceki panel işlemleri güvenli biçimde durdurulamadı.
    goto :error
)

set "STATE_DIR=%APPDATA%\PCActivityMonitor"
set "VENV_DIR=%STATE_DIR%\venv"
echo.
echo [3/5] Önceki ortam ve eski etkinlik günlükleri kaldırılıyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$state = Join-Path $env:APPDATA 'PCActivityMonitor'; $venv = Join-Path $state 'venv'; if (Test-Path -LiteralPath $venv) { Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction Stop }; foreach ($name in @('bot.log', 'client.log', 'discord.log', 'startup.log', 'startup_launcher.log', 'status_message.json')) { $path = Join-Path $state $name; if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force -ErrorAction Stop } }"
if errorlevel 1 (
    echo [HATA] Eski yerel ortam ve günlükler güvenli biçimde temizlenemedi.
    goto :error
)
echo.
echo Yeni bir özel Python ortamı oluşturuluyor ve bağımlılıklar kuruluyor...
"%PYTHON_EXE%" -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [HATA] Özel Python ortamı oluşturulamadı.
    goto :error
)
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [HATA] Özel Python ortamında pip hazırlanamadı.
    goto :error
)
"%VENV_DIR%\Scripts\python.exe" -m pip install discord.py psutil pystray Pillow
if errorlevel 1 (
    echo [HATA] Paket kurulumu başarısız oldu.
    goto :error
)
"%VENV_DIR%\Scripts\python.exe" "%APP_DIR%\setup_config.py" --set-pythonw-path "%VENV_DIR%\Scripts\pythonw.exe"
if errorlevel 1 (
    echo [HATA] Özel Python çalışma zamanı yolu kaydedilemedi.
    goto :error
)

echo.
echo [4/5] Bu Windows kullanıcısı için otomatik başlangıç kaydediliyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\register_startup.ps1" -LauncherPath "%APP_DIR%\start_hidden.vbs"
if errorlevel 1 (
    echo [HATA] Panel bu kullanıcının Başlangıç klasörüne eklenemedi.
    goto :error
)

echo.
echo [5/5] Bilgisayar kontrol paneli başlatılıyor...
"%VENV_DIR%\Scripts\python.exe" "%APP_DIR%\start_services.py" --wait
if errorlevel 1 (
    echo.
    echo [HATA] Bilgisayar kontrol paneli hazır olmadı.
    echo Günlük klasörü: "%APPDATA%\PCActivityMonitor"
    echo Başlangıç, istemci ve Discord günlüklerinin son satırları yukarıda gösterildi.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [BAŞARILI] Kurulum tamamlandı.
echo ============================================================
echo Discord kontrol paneli arka planda çalışıyor.
echo Embed düğmelerini kullanmak için özel Discord kontrol kanalını açın.
echo Günlükler: "%APPDATA%\PCActivityMonitor"
echo Yeniden yapılandırmak veya kaldırmak için setup.bat dosyasını yeniden çalıştırın.
echo Bu kurulum penceresini kapatabilirsiniz.
exit /b 0

:error
echo.
echo Kurulum tamamlanamadı. Yukarıdaki hatayı giderip setup.bat dosyasını yeniden çalıştırın.
pause
exit /b 1
