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


APP_NAME = "PCActivityMonitor"
CONSENT_NOTICE_VERSION = "2026-10-29-discord-control-app-list"
STATE_DIR = Path(os.environ["APPDATA"]) / APP_NAME
CONFIG_FILE = STATE_DIR / "config.json"
READY_FILE = STATE_DIR / "discord_ready.json"
START_LOCK_FILE = STATE_DIR / "client_start.lock"
STARTUP_LOG = STATE_DIR / "startup.log"
APP_DIR = Path(__file__).resolve().parent
CLIENT_SCRIPT = os.path.normcase(os.path.abspath(APP_DIR / "client.py"))


def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with STARTUP_LOG.open("a", encoding="utf-8") as output:
        output.write(f"[{timestamp}] {message}\n")


def read_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as source:
        config = json.load(source)
    consent = config.get("CONSENT")
    if (
        not config.get("BOT_TOKEN")
        or int(config.get("ALLOWED_USER_ID", 0)) <= 0
        or int(config.get("GUILD_ID", 0)) <= 0
        or int(config.get("CHANNEL_ID", 0)) <= 0
        or not isinstance(consent, dict)
        or not consent.get("accepted_at_utc")
        or consent.get("notice_version") != CONSENT_NOTICE_VERSION
    ):
        raise ValueError("Kurulum yapılandırması veya kullanıcı onayı eksik.")
    return config


def find_client_process():
    for process in psutil.process_iter(["cmdline"]):
        try:
            if process_matches_client(process):
                return process
        except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def process_matches_client(process):
    try:
        command_line = getattr(process, "info", {}).get("cmdline")
        if command_line is None:
            command_line = process.cmdline()
        return any(
            os.path.normcase(os.path.abspath(argument)) == CLIENT_SCRIPT
            for argument in command_line or []
        )
    except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def process_is_running(process):
    if isinstance(process, subprocess.Popen):
        return process.poll() is None
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (OSError, psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def client_is_ready(process):
    if not process_is_running(process):
        return False
    try:
        with READY_FILE.open("r", encoding="utf-8") as ready_file:
            ready = json.load(ready_file)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(ready, dict)
        and ready.get("pid") == process.pid
        and process_matches_client(process)
    )


def find_ready_client_process():
    try:
        with READY_FILE.open("r", encoding="utf-8") as ready_file:
            ready = json.load(ready_file)
        process_id = ready.get("pid") if isinstance(ready, dict) else None
        if not isinstance(process_id, int):
            return None
        process = psutil.Process(process_id)
    except (OSError, psutil.NoSuchProcess, psutil.AccessDenied, json.JSONDecodeError):
        return None
    return process if client_is_ready(process) else None


def start_client(python_path):
    output_path = STATE_DIR / "client.log"
    with output_path.open("a", encoding="utf-8") as output:
        return subprocess.Popen(
            [str(python_path), str(APP_DIR / "client.py")],
            cwd=str(APP_DIR),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def start_or_find_client(python_path):
    with START_LOCK_FILE.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            process = find_client_process()
            if process is not None:
                return process, False
            READY_FILE.unlink(missing_ok=True)
            return start_client(python_path), True
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def print_recent_logs(log_names, line_limit=30):
    print(f"\nLog klasörü: {STATE_DIR}")
    for log_name in log_names:
        log_path = STATE_DIR / log_name
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    try:
        read_config()
        pythonw_path = Path(
            (STATE_DIR / "pythonw_path.txt").read_text(encoding="utf-16").strip()
        )
        if not pythonw_path.is_file():
            raise FileNotFoundError(f"pythonw.exe bulunamadı: {pythonw_path}")
        python_path = pythonw_path.with_name("python.exe")
        if not python_path.is_file():
            raise FileNotFoundError(f"python.exe bulunamadı: {python_path}")

        process, started = start_or_find_client(python_path)
        if started:
            log("Discord kontrol botuyla PC istemcisi başlatıldı.")
        else:
            log(f"Çalışan PC istemcisi bulundu (PID {process.pid}).")

        if not args.wait:
            return 0

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready_process = find_ready_client_process()
            if ready_process is not None:
                print("Discord PC kontrol botu hazır; butonlu Embed gönderildi.")
                print(f"Loglar: {STATE_DIR}")
                return 0
            if find_client_process() is None and not process_is_running(process):
                break
            time.sleep(1)

        message = "Discord kontrol botu hazır olmadı; başlangıç loglarını kontrol et."
        log(message)
        print(message, file=sys.stderr)
        print_recent_logs(("startup.log", "client.log", "discord.log"))
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        message = f"Servis başlatılamadı: {exc}"
        try:
            log(message)
        except OSError:
            pass
        print(message, file=sys.stderr)
        print_recent_logs(("startup.log", "client.log", "discord.log"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
