import argparse
from collections import deque
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


UYGULAMA_ADI = "PCActivityMonitor"
ONAY_SURUMU = "2026-11-10-reminders-and-controls"
DURUM_DIZINI = Path(os.environ["APPDATA"]) / UYGULAMA_ADI
AYAR_DOSYASI = DURUM_DIZINI / "config.json"
HAZIRLIK_DOSYASI = DURUM_DIZINI / "discord_ready.json"
BASLATMA_KILIT_DOSYASI = DURUM_DIZINI / "client_start.lock"
BASLANGIC_GUNLUGU = DURUM_DIZINI / "startup.log"
UYGULAMA_DIZINI = Path(__file__).resolve().parent
ISTEMCI_BETIGI = os.path.normcase(os.path.abspath(UYGULAMA_DIZINI / "client.py"))


def baslangic_logu_yaz(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with BASLANGIC_GUNLUGU.open("a", encoding="utf-8") as output:
        output.write(f"[{timestamp}] {message}\n")


def ayarlari_oku():
    with AYAR_DOSYASI.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise ValueError(
            "Kurulum yapılandırması geçersiz. setup.bat içinden 1 ile yeniden yapılandırın."
        )
    if (
        not config.get("BOT_TOKEN")
        or int(config.get("ALLOWED_USER_ID", 0)) <= 0
        or int(config.get("GUILD_ID", 0)) <= 0
        or int(config.get("CHANNEL_ID", 0)) <= 0
    ):
        raise ValueError(
            "Kurulum ayarları eksik. setup.bat içinden 1 ile yeniden yapılandırın."
        )

    consent = config.get("CONSENT")
    if not isinstance(consent, dict) or not consent.get("accepted_at_utc"):
        raise ValueError(
            "Gizlilik onayı bulunamadı. setup.bat içinden 1 ile yeniden yapılandırıp "
            "bildirimi okuyarak onaylayın."
        )
    if consent.get("notice_version") != ONAY_SURUMU:
        raise ValueError(
            "Gizlilik bildirimi kurulumdan sonra güncellendi. setup.bat içinden 1'i seçin, "
            "kayıtlı token ve ID'lerle devam edin, yeni bildirimi okuyup onaylayın."
        )
    return config


def istemci_surecini_bul():
    for process in psutil.process_iter(["cmdline"]):
        try:
            if surec_istemciyle_eslesiyor(process):
                return process
        except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def surec_istemciyle_eslesiyor(process):
    try:
        command_line = getattr(process, "info", {}).get("cmdline")
        if command_line is None:
            command_line = process.cmdline()
        return any(
            os.path.normcase(os.path.abspath(argument)) == ISTEMCI_BETIGI
            for argument in command_line or []
        )
    except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def surec_calismaya_devam_ediyor(process):
    if isinstance(process, subprocess.Popen):
        return process.poll() is None
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def istemci_hazir_mi(process):
    if not surec_calismaya_devam_ediyor(process):
        return False
    try:
        with HAZIRLIK_DOSYASI.open("r", encoding="utf-8") as ready_file:
            ready = json.load(ready_file)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(ready, dict)
        and ready.get("pid") == process.pid
        and surec_istemciyle_eslesiyor(process)
    )


def hazir_istemci_surecini_bul():
    try:
        with HAZIRLIK_DOSYASI.open("r", encoding="utf-8") as ready_file:
            ready = json.load(ready_file)
        process_id = ready.get("pid") if isinstance(ready, dict) else None
        if not isinstance(process_id, int):
            return None
        process = psutil.Process(process_id)
    except (OSError, psutil.NoSuchProcess, psutil.AccessDenied, json.JSONDecodeError):
        return None
    return process if istemci_hazir_mi(process) else None


def istemciyi_baslat(python_path):
    output_path = DURUM_DIZINI / "client.log"
    with output_path.open("a", encoding="utf-8") as output:
        return subprocess.Popen(
            [str(python_path), str(UYGULAMA_DIZINI / "client.py")],
            cwd=str(UYGULAMA_DIZINI),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def istemciyi_baslat_veya_bul(python_path):
    with BASLATMA_KILIT_DOSYASI.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            process = istemci_surecini_bul()
            if process is not None:
                return process, False
            HAZIRLIK_DOSYASI.unlink(missing_ok=True)
            return istemciyi_baslat(python_path), True
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def son_loglari_goster(log_names, line_limit=30):
    print(f"\nGünlük klasörü: {DURUM_DIZINI}")
    for log_name in log_names:
        log_path = DURUM_DIZINI / log_name
        print(f"\n--- {log_path} (son {line_limit} satır) ---")
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as log_file:
                lines = deque(log_file, maxlen=line_limit)
        except OSError as exc:
            print(f"Log okunamadı: {exc}")
            continue
        if not lines:
            print("(boş)")
            continue
        print("".join(lines), end="")


def ana():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", action="store_true")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Servisi durdurmadan önce kurulum ve gizlilik onayını doğrular.",
    )
    args = parser.parse_args()
    if args.check_config:
        try:
            ayarlari_oku()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Yapılandırma doğrulaması başarısız: {exc}", file=sys.stderr)
            return 1
        print("Kurulum yapılandırması ve gizlilik onayı güncel.")
        return 0

    try:
        ayarlari_oku()
        pythonw_path = Path(
            (DURUM_DIZINI / "pythonw_path.txt").read_text(encoding="utf-16").strip()
        )
        if not pythonw_path.is_file():
            raise FileNotFoundError(f"pythonw.exe bulunamadı: {pythonw_path}")
        python_path = pythonw_path.with_name("python.exe")
        if not python_path.is_file():
            raise FileNotFoundError(f"python.exe bulunamadı: {python_path}")

        process, started = istemciyi_baslat_veya_bul(python_path)
        if started:
            baslangic_logu_yaz("Discord kontrol botuyla PC istemcisi başlatıldı.")
        else:
            baslangic_logu_yaz(f"Çalışan PC istemcisi bulundu (PID {process.pid}).")

        if not args.wait:
            return 0

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready_process = hazir_istemci_surecini_bul()
            if ready_process is not None:
                print("Discord PC kontrol botu hazır; butonlu Embed gönderildi.")
                print(f"Günlükler: {DURUM_DIZINI}")
                return 0
            if istemci_surecini_bul() is None and not surec_calismaya_devam_ediyor(process):
                break
            time.sleep(1)

        message = "Discord kontrol botu hazır olmadı; başlangıç loglarını kontrol et."
        baslangic_logu_yaz(message)
        print(message, file=sys.stderr)
        son_loglari_goster(("startup.log", "client.log", "discord.log"))
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        message = f"Servis başlatılamadı: {exc}"
        try:
            baslangic_logu_yaz(message)
        except OSError:
            pass
        print(message, file=sys.stderr)
        son_loglari_goster(("startup.log", "client.log", "discord.log"))
        return 1


if __name__ == "__main__":
    raise SystemExit(ana())
