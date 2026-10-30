import io
import logging
from logging.handlers import RotatingFileHandler
import msvcrt
import os
from pathlib import Path
import platform
import socket
import subprocess
import threading
import time
from datetime import datetime

import psutil
import pystray
from PIL import Image, ImageDraw, ImageGrab


APP_NAME = "PCActivityMonitor"
STATE_DIR = Path(os.environ["APPDATA"]) / APP_NAME
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = STATE_DIR / "client.log"
INSTANCE_LOCK_FILE = STATE_DIR / "client_instance.lock"
logger = logging.getLogger("pc_self_control")
logger.setLevel(logging.INFO)
logger.addHandler(
    RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
)

ACTION_LOCK = threading.Lock()
pending_action = None
pending_action_until = 0
shutdown_event = threading.Event()


def acquire_instance_lock():
    lock_file = INSTANCE_LOCK_FILE.open("a+b")
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    lock_file.seek(0)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def get_open_applications():
    import ctypes
    from ctypes import wintypes

    load_library = getattr(ctypes, "WinDLL", None)
    if load_library is None:
        return [], 0

    user32 = load_library("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    process_windows = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect_window(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        process_id = wintypes.DWORD()
        if user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)):
            process_windows[process_id.value] = process_windows.get(process_id.value, 0) + 1
        return True

    if not user32.EnumWindows(collect_window, 0):
        raise ctypes.WinError(ctypes.get_last_error())

    applications = {}
    unavailable = 0
    for process_id, window_count in process_windows.items():
        try:
            name = Path(psutil.Process(process_id).name()).stem
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            unavailable += 1
            continue
        applications[name] = applications.get(name, 0) + window_count

    return (
        [
            f"{name} ({count} pencere)" if count > 1 else name
            for name, count in sorted(applications.items(), key=lambda item: item[0].casefold())
        ],
        unavailable,
    )


def collect_status():
    global pending_action, pending_action_until
    try:
        cpu = round(psutil.cpu_percent(interval=None))
        memory = round(psutil.virtual_memory().percent)
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        disk = psutil.disk_usage(drive)
        boot_timestamp = psutil.boot_time()
        uptime_seconds = max(0, int(time.time() - boot_timestamp))
        cpu_frequency = psutil.cpu_freq()
        battery = psutil.sensors_battery()
        memory_stats = psutil.virtual_memory()
    except (OSError, psutil.Error) as exc:
        logger.exception("Could not collect system status.")
        raise RuntimeError("Bilgisayar durumu okunamadı.") from exc

    with ACTION_LOCK:
        if pending_action and time.time() >= pending_action_until:
            pending_action = None
            pending_action_until = 0
        pending_seconds = max(0, int(pending_action_until - time.time()))
        current_action = pending_action
    try:
        applications, unavailable_applications = get_open_applications()
        applications_error = None
    except (OSError, psutil.Error, RuntimeError):
        logger.exception("Could not read open Windows applications.")
        applications, unavailable_applications = [], 0
        applications_error = "Uygulama listesi alınamadı; hata client.log dosyasına kaydedildi."

    return {
        "hostname": socket.gethostname(),
        "username": os.environ.get("USERNAME", "Windows kullanıcısı"),
        "cpu": cpu,
        "cpu_model": platform.processor() or platform.machine() or "Windows işlemci",
        "cpu_cores": psutil.cpu_count(logical=False) or psutil.cpu_count() or 1,
        "cpu_threads": psutil.cpu_count(logical=True) or 1,
        "os_name": f"{platform.system()} {platform.release()}",
        "ram": memory,
        "cpu_frequency_mhz": (
            round(cpu_frequency.current) if cpu_frequency is not None else None
        ),
        "ram_used_gb": round(memory_stats.used / (1024 ** 3), 1),
        "ram_total_gb": round(memory_stats.total / (1024 ** 3), 1),
        "ram_available_gb": round(memory_stats.available / (1024 ** 3), 1),
        "disk_used": round(disk.percent),
        "disk_free_gb": round(disk.free / (1024 ** 3), 1),
        "disk_total_gb": round(disk.total / (1024 ** 3), 1),
        "uptime_seconds": uptime_seconds,
        "boot_time": datetime.fromtimestamp(boot_timestamp).astimezone().strftime(
            "%d.%m.%Y %H:%M"
        ),
        "battery": (
            f"{battery.percent}%"
            + (" · şarj oluyor" if battery.power_plugged else " · pilde")
            if battery is not None
            else "Masaüstü / pil bilgisi yok"
        ),
        "applications": applications,
        "unavailable_applications": unavailable_applications,
        "applications_error": applications_error,
        "pending_action": current_action,
        "pending_seconds": pending_seconds,
    }


def format_duration(seconds):
    total_minutes = max(0, int(seconds)) // 60
    days, remaining_hours = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_hours, 60)
    parts = []
    if days:
        parts.append(f"{days} gün")
    if hours:
        parts.append(f"{hours} saat")
    if minutes or not parts:
        parts.append(f"{minutes} dakika")
    return " ".join(parts)


def capture_screenshot():
    screenshot = ImageGrab.grab(all_screens=True)
    screenshot.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
    converted = screenshot.convert("RGB")
    output = io.BytesIO()
    quality = 68
    while True:
        output.seek(0)
        output.truncate()
        converted.save(output, format="JPEG", quality=quality, optimize=True)
        if output.tell() <= 7_500_000:
            break
        if quality > 40:
            quality -= 8
        else:
            converted.thumbnail(
                (max(640, int(converted.width * 0.8)), max(480, int(converted.height * 0.8))),
                Image.Resampling.LANCZOS,
            )
            quality = 60
    output.seek(0)
    return output


def run_power_action(action):
    global pending_action, pending_action_until
    shutdown_exe = Path(os.environ["SystemRoot"]) / "System32" / "shutdown.exe"
    if not shutdown_exe.is_file():
        raise OSError("Windows shutdown.exe bulunamadı.")

    with ACTION_LOCK:
        if action in ("restart", "shutdown"):
            if pending_action:
                raise ValueError("Zaten planlanmış bir güç işlemi var; önce iptal et.")
            command = [str(shutdown_exe), "/r" if action == "restart" else "/s", "/t", "60",
                       "/c", "Scheduled from the authorized Discord control panel"]
            message = (
                "Yeniden başlatma 60 saniye sonrasına planlandı."
                if action == "restart"
                else "Bilgisayarın kapanması 60 saniye sonrasına planlandı."
            )
        elif action == "cancel":
            if not pending_action:
                raise ValueError("İptal edilecek planlanmış bir işlem yok.")
            command = [str(shutdown_exe), "/a"]
            message = "Planlanan güç işlemi iptal edildi."
        else:
            raise ValueError("Desteklenmeyen güç işlemi.")

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise OSError(detail or f"shutdown.exe {result.returncode} koduyla başarısız oldu.")
        if action == "cancel":
            pending_action = None
            pending_action_until = 0
        else:
            pending_action = action
            pending_action_until = time.time() + 60
        return message


def tray_image():
    image = Image.new("RGBA", (64, 64), (14, 24, 40, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, 54, 54), radius=12, fill=(66, 133, 244, 255))
    draw.rectangle((20, 20, 44, 24), fill="white")
    draw.rectangle((20, 29, 44, 33), fill="white")
    draw.rectangle((20, 38, 37, 42), fill="white")
    return image


def quit_application(icon, item):
    logger.info("%s selected from the tray menu.", item.text)
    shutdown_event.set()
    icon.stop()
    try:
        from discord_control import stop_bot

        stop_bot()
    except ImportError:
        logger.exception("Could not import Discord bot shutdown handler.")


def disable_startup_and_quit(icon, item):
    logger.info("%s selected from the tray menu.", item.text)
    shortcut = (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "PCActivityMonitor.lnk"
    )
    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$task = Get-ScheduledTask -TaskName 'PCActivityMonitor' "
        "-ErrorAction SilentlyContinue; "
        "if ($null -ne $task) { "
        "Unregister-ScheduledTask -InputObject $task -Confirm:$false -ErrorAction Stop }"
    )
    try:
        shortcut.unlink(missing_ok=True)
        result = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise OSError(detail or "Başlangıç görevi kaldırılamadı.")
    except OSError:
        logger.exception("Could not disable automatic startup.")
        return
    quit_application(icon, item)


def start_tray():
    try:
        icon = pystray.Icon(
            "PCSelfControl",
            tray_image(),
            "Discord PC Kontrolü",
            pystray.Menu(
                pystray.MenuItem("Oturum sonuna kadar kapat", quit_application),
                pystray.MenuItem("Başlangıcı kapat ve çık", disable_startup_and_quit),
            ),
        )
        icon.run()
    except Exception:
        logger.exception("Could not show the system tray controls.")


def main():
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        logger.info("Another PC control client instance is already running.")
        return

    threading.Thread(target=start_tray, daemon=True).start()
    from discord_control import run_bot

    threading.Thread(target=run_bot, name="discord-control-bot", daemon=True).start()
    try:
        shutdown_event.wait()
    finally:
        from discord_control import clear_ready

        clear_ready()
        instance_lock.close()


if __name__ == "__main__":
    main()
