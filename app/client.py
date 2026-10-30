from contextlib import closing
from datetime import datetime
from logging.handlers import RotatingFileHandler

import io
import logging
import msvcrt
import os
from pathlib import Path
import platform
import sqlite3
import socket
import subprocess
import threading
import time

import psutil
import pystray
from PIL import Image, ImageDraw, ImageGrab


UYGULAMA_ADI = "PCActivityMonitor"
DURUM_DIZINI = Path(os.environ["APPDATA"]) / UYGULAMA_ADI
DURUM_DIZINI.mkdir(parents=True, exist_ok=True)
GUNLUK_DOSYASI = DURUM_DIZINI / "client.log"
TEKIL_ORNEK_KILIT_DOSYASI = DURUM_DIZINI / "client_instance.lock"
GECMIS_DOSYASI = DURUM_DIZINI / "metrics.sqlite3"
GECMIS_SAKLAMA_SANIYESI = 7 * 24 * 60 * 60
GECMIS_ORNEK_ARALIGI_SANIYE = 30
logger = logging.getLogger("pc_kisisel_kontrol")
logger.setLevel(logging.INFO)
logger.addHandler(
    RotatingFileHandler(GUNLUK_DOSYASI, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
)

ISLEM_KILIDI = threading.Lock()
AG_KILIDI = threading.Lock()
bekleyen_guc_islemi = None
bekleyen_islem_bitis_zamani = 0
kapatma_olayi = threading.Event()
onceki_ag_ornegi = None


def tekil_ornek_kilidi_al():
    lock_file = TEKIL_ORNEK_KILIT_DOSYASI.open("a+b")
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


def acik_uygulamalari_topla():
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


def uygulama_kapat(uygulama_adi):
    temiz_ad = uygulama_adi.split(" (")[0].strip().lower()
    kapatilan = 0
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            p_name = Path(proc.info['name']).stem.lower()
            if p_name == temiz_ad:
                psutil.Process(proc.info['pid']).terminate()
                kapatilan += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if kapatilan == 0:
        raise ValueError(f"'{uygulama_adi}' adında çalışan aktif bir süreç bulunamadı.")
    return f"'{uygulama_adi}' başarıyla sonlandırıldı."


def kaynak_tuketimindeki_surecleri_getir(memory_total):
    surecler = []
    okunamayan_surec = 0
    for surec in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            bilgi = surec.info
            ad = bilgi.get("name")
            bellek_bilgisi = bilgi.get("memory_info")
            if not ad or bellek_bilgisi is None:
                continue
            surecler.append(
                {
                    "ad": Path(ad).stem,
                    "cpu": round(float(bilgi.get("cpu_percent") or 0.0), 1),
                    "bellek_mb": round(bellek_bilgisi.rss / (1024 ** 2), 1),
                    "bellek_yuzde": round(bellek_bilgisi.rss / memory_total * 100, 1),
                }
            )
        except (OSError, psutil.Error):
            okunamayan_surec += 1
    surecler.sort(key=lambda surec: (surec["bellek_mb"], surec["cpu"]), reverse=True)
    return surecler[:5], okunamayan_surec


def ag_ozetini_topla():
    global onceki_ag_ornegi
    sayaclar = psutil.net_io_counters()
    if sayaclar is None:
        raise RuntimeError("Ağ trafiği sayaçları okunamadı.")
    arayuzler = psutil.net_if_stats()

    simdi = time.monotonic()
    with AG_KILIDI:
        onceki = onceki_ag_ornegi
        onceki_ag_ornegi = (
            simdi,
            sayaclar.bytes_sent,
            sayaclar.bytes_recv,
        )
    if onceki is None or simdi <= onceki[0]:
        gonderim_hizi = None
        alim_hizi = None
    else:
        gecen_sure = simdi - onceki[0]
        gonderim_hizi = max(0, sayaclar.bytes_sent - onceki[1]) / gecen_sure
        alim_hizi = max(0, sayaclar.bytes_recv - onceki[2]) / gecen_sure
    return {
        "etkin_arayuz_sayisi": sum(1 for arayuz in arayuzler.values() if arayuz.isup),
        "gonderilen_bayt": sayaclar.bytes_sent,
        "alinan_bayt": sayaclar.bytes_recv,
        "gonderim_hizi": gonderim_hizi,
        "alim_hizi": alim_hizi,
    }


def boyutu_bicimlendir(bayt):
    deger = float(bayt)
    for birim in ("B", "KB", "MB", "GB", "TB"):
        if deger < 1024 or birim == "TB":
            return f"{deger:.1f} {birim}"
        deger /= 1024


def gecmisi_kaydet(cpu, bellek, disk):
    simdi = time.time()
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            baglanti.execute(
                """
                CREATE TABLE IF NOT EXISTS kaynak_gecmisi (
                    kayit_zamani REAL PRIMARY KEY,
                    cpu REAL NOT NULL,
                    bellek REAL NOT NULL,
                    disk REAL NOT NULL
                )
                """
            )
            son_kayit = baglanti.execute(
                "SELECT MAX(kayit_zamani) FROM kaynak_gecmisi"
            ).fetchone()[0]
            if son_kayit is None or simdi - son_kayit >= GECMIS_ORNEK_ARALIGI_SANIYE:
                baglanti.execute(
                    """
                    INSERT INTO kaynak_gecmisi
                    (kayit_zamani, cpu, bellek, disk)
                    VALUES (?, ?, ?, ?)
                    """,
                    (simdi, cpu, bellek, disk),
                )
            baglanti.execute(
                "DELETE FROM kaynak_gecmisi WHERE kayit_zamani < ?",
                (simdi - GECMIS_SAKLAMA_SANIYESI,),
            )
            baglanti.commit()
    except sqlite3.Error:
        logger.exception("Kaynak kullanım geçmişi yerel veritabanına kaydedilemedi.")
        return "Geçmiş veritabanına kaydedilemedi; client.log dosyasını inceleyin."
    return None


def gecmis_verilerini_getir(saat=1):
    if not 1 <= saat <= 168:
        raise ValueError("Geçmiş aralığı 1 ile 168 saat arasında olmalıdır.")
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            satirlar = baglanti.execute(
                """
                SELECT kayit_zamani, cpu, bellek, disk
                FROM kaynak_gecmisi
                WHERE kayit_zamani >= ?
                ORDER BY kayit_zamani
                """,
                (time.time() - saat * 60 * 60,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.exception("Kaynak kullanım geçmişi okunamadı.")
        raise RuntimeError("Kaynak kullanım geçmişi okunamadı.") from exc
    return satirlar


def gecmis_grafigi_olustur(saat=1):
    satirlar = gecmis_verilerini_getir(saat)
    genislik, yukseklik = 1200, 650
    sol, ust, sag, alt = 90, 90, 1140, 550
    gorsel = Image.new("RGB", (genislik, yukseklik), "#101827")
    cizim = ImageDraw.Draw(gorsel)
    cizim.text((sol, 28), f"Son {saat} saat • Sistem kaynak geçmişi", fill="#ffffff")
    cizim.text((sol, 58), "CPU, bellek ve disk kullanımı (%)", fill="#aab8ca")

    for deger in range(0, 101, 20):
        y = alt - (alt - ust) * deger / 100
        cizim.line((sol, y, sag, y), fill="#34445a", width=1)
        cizim.text((42, y - 7), str(deger), fill="#aab8ca")

    if len(satirlar) < 2:
        cizim.text((sol, 300), "Grafik için henüz yeterli geçmiş verisi yok.", fill="#ffffff")
        cizim.text((sol, 330), "Veriler yerel olarak 7 güne kadar saklanır.", fill="#aab8ca")
    else:
        renkler = ("#4da3ff", "#53d18c", "#ffba52")
        for sutun, renk in zip((1, 2, 3), renkler):
            noktalar = []
            for sira, satir in enumerate(satirlar):
                x = sol + (sag - sol) * sira / (len(satirlar) - 1)
                y = alt - (alt - ust) * min(100, max(0, satir[sutun])) / 100
                noktalar.append((x, y))
            cizim.line(noktalar, fill=renk, width=4)
        for x, yazi in ((sol, "En eski"), (sag - 55, "Şimdi")):
            cizim.text((x, alt + 18), yazi, fill="#aab8ca")
        for sira, (etiket, renk) in enumerate(
            (("CPU", renkler[0]), ("Bellek", renkler[1]), ("Disk", renkler[2]))
        ):
            x = sol + sira * 150
            cizim.line((x, yukseklik - 25, x + 24, yukseklik - 25), fill=renk, width=4)
            cizim.text((x + 32, yukseklik - 32), etiket, fill="#ffffff")
    cikti = io.BytesIO()
    gorsel.save(cikti, format="PNG", optimize=True)
    cikti.seek(0)
    return cikti


def durum_topla():
    global bekleyen_guc_islemi, bekleyen_islem_bitis_zamani
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
        logger.exception("Bilgisayar durumu toplanamadı.")
        raise RuntimeError("Bilgisayar durumu okunamadı.") from exc

    try:
        ag = ag_ozetini_topla()
        ag_hatasi = None
    except (OSError, psutil.Error, RuntimeError):
        logger.exception("Ağ trafiği bilgileri okunamadı.")
        ag = None
        ag_hatasi = "Ağ trafiği bilgisi alınamadı; client.log dosyasını inceleyin."
    try:
        en_cok_kullanan_surecler, okunamayan_surec = (
            kaynak_tuketimindeki_surecleri_getir(memory_stats.total)
        )
        surec_hatasi = None
    except (OSError, psutil.Error):
        logger.exception("Kaynak tüketen süreçler okunamadı.")
        en_cok_kullanan_surecler, okunamayan_surec = [], 0
        surec_hatasi = "Süreç listesi alınamadı; client.log dosyasını inceleyin."

    with ISLEM_KILIDI:
        if bekleyen_guc_islemi and time.time() >= bekleyen_islem_bitis_zamani:
            bekleyen_guc_islemi = None
            bekleyen_islem_bitis_zamani = 0
        pending_seconds = max(0, int(bekleyen_islem_bitis_zamani - time.time()))
        current_action = bekleyen_guc_islemi
    try:
        applications, unavailable_applications = acik_uygulamalari_topla()
        applications_error = None
    except (OSError, psutil.Error, RuntimeError):
        logger.exception("Açık Windows uygulamaları okunamadı.")
        applications, unavailable_applications = [], 0
        applications_error = "Uygulama listesi alınamadı; hata client.log dosyasına kaydedildi."

    history_error = gecmisi_kaydet(cpu, memory, disk.percent)
    return {
        "bilgisayar_adi": socket.gethostname(),
        "kullanici_adi": os.environ.get("USERNAME", "Windows kullanıcısı"),
        "cpu": cpu,
        "cpu_modeli": platform.processor() or platform.machine() or "Windows işlemci",
        "cpu_cekirdek": psutil.cpu_count(logical=False) or psutil.cpu_count() or 1,
        "cpu_izlek": psutil.cpu_count(logical=True) or 1,
        "isletim_sistemi": f"{platform.system()} {platform.release()}",
        "bellek_yuzde": memory,
        "cpu_frekans_mhz": (
            round(cpu_frequency.current) if cpu_frequency is not None else None
        ),
        "bellek_kullanilan_gb": round(memory_stats.used / (1024 ** 3), 1),
        "bellek_toplam_gb": round(memory_stats.total / (1024 ** 3), 1),
        "bellek_kullanilabilir_gb": round(memory_stats.available / (1024 ** 3), 1),
        "disk_kullanilan_yuzde": round(disk.percent),
        "disk_bos_gb": round(disk.free / (1024 ** 3), 1),
        "disk_toplam_gb": round(disk.total / (1024 ** 3), 1),
        "calisma_suresi_saniye": uptime_seconds,
        "baslangic_zamani": datetime.fromtimestamp(boot_timestamp).astimezone().strftime(
            "%d.%m.%Y %H:%M"
        ),
        "pil_durumu": (
            f"{battery.percent}%"
            + (" · şarj oluyor" if battery.power_plugged else " · pilde")
            if battery is not None
            else "Masaüstü / pil bilgisi yok"
        ),
        "acik_uygulamalar": applications,
        "okunamayan_uygulama_sayisi": unavailable_applications,
        "uygulama_hatasi": applications_error,
        "en_cok_kullanan_surecler": en_cok_kullanan_surecler,
        "okunamayan_surec_sayisi": okunamayan_surec,
        "surec_hatasi": surec_hatasi,
        "ag": ag,
        "ag_hatasi": ag_hatasi,
        "gecmis_hatasi": history_error,
        "bekleyen_islem": current_action,
        "bekleyen_islem_saniye": pending_seconds,
    }


def sureyi_bicimlendir(seconds):
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


def ekran_goruntusu_al():
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


def guc_islemi_yurut(islem):
    global bekleyen_guc_islemi, bekleyen_islem_bitis_zamani
    shutdown_exe = Path(os.environ["SystemRoot"]) / "System32" / "shutdown.exe"
    if not shutdown_exe.is_file():
        raise OSError("Windows shutdown.exe bulunamadı.")

    with ISLEM_KILIDI:
        if islem in ("restart", "shutdown"):
            if bekleyen_guc_islemi:
                raise ValueError("Zaten planlanmış bir güç işlemi var; önce iptal et.")
            command = [str(shutdown_exe), "/r" if islem == "restart" else "/s", "/t", "60",
                       "/c", "Yetkili Discord kontrol panelinden planlandı"]
            message = (
                "Yeniden başlatma 60 saniye sonrasına planlandı."
                if islem == "restart"
                else "Bilgisayarın kapanması 60 saniye sonrasına planlandı."
            )
        elif islem == "cancel":
            if not bekleyen_guc_islemi:
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
        if islem == "cancel":
            bekleyen_guc_islemi = None
            bekleyen_islem_bitis_zamani = 0
        else:
            bekleyen_guc_islemi = islem
            bekleyen_islem_bitis_zamani = time.time() + 60
        return message


def tepsi_gorselini_olustur():
    image = Image.new("RGBA", (64, 64), (14, 24, 40, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, 54, 54), radius=12, fill=(66, 133, 244, 255))
    draw.rectangle((20, 20, 44, 24), fill="white")
    draw.rectangle((20, 29, 44, 33), fill="white")
    draw.rectangle((20, 38, 37, 42), fill="white")
    return image


def uygulamadan_cik(icon, item):
    logger.info("Tepsi menüsünden seçildi: %s", item.text)
    kapatma_olayi.set()
    icon.stop()
    try:
        from discord_control import botu_durdur

        botu_durdur()
    except ImportError:
        logger.exception("Discord botunu durdurma işlevi içe aktarılamadı.")


def baslangici_kapat_ve_cik(icon, item):
    logger.info("Tepsi menüsünden seçildi: %s", item.text)
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
        logger.exception("Otomatik başlangıç devre dışı bırakılamadı.")
        return
    uygulamadan_cik(icon, item)


def tepsi_menusunu_baslat():
    try:
        icon = pystray.Icon(
            "PCSelfControl",
            tepsi_gorselini_olustur(),
            "Discord PC Kontrolü",
            pystray.Menu(
                pystray.MenuItem("Oturum sonuna kadar kapat", uygulamadan_cik),
                pystray.MenuItem("Başlangıcı kapat ve çık", baslangici_kapat_ve_cik),
            ),
        )
        icon.run()
    except Exception:
        logger.exception("Sistem tepsisi denetimleri gösterilemedi.")


def ana():
    instance_lock = tekil_ornek_kilidi_al()
    if instance_lock is None:
        logger.info("PC kontrol istemcisinin başka bir örneği zaten çalışıyor.")
        return

    threading.Thread(target=tepsi_menusunu_baslat, daemon=True).start()
    from discord_control import botu_calistir

    threading.Thread(target=botu_calistir, name="discord-kontrol-botu", daemon=True).start()
    try:
        kapatma_olayi.wait()
    finally:
        from discord_control import hazirlik_durumunu_temizle

        hazirlik_durumunu_temizle()
        instance_lock.close()


if __name__ == "__main__":
    ana()