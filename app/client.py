from contextlib import closing
from datetime import datetime
from logging.handlers import RotatingFileHandler

import io
from datetime import date, datetime, timedelta
import ipaddress
import json
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
AYAR_DOSYASI = DURUM_DIZINI / "config.json"
GUNLUK_DOSYASI = DURUM_DIZINI / "client.log"
TEKIL_ORNEK_KILIT_DOSYASI = DURUM_DIZINI / "client_instance.lock"
GECMIS_DOSYASI = DURUM_DIZINI / "metrics.sqlite3"
GECMIS_SAKLAMA_SANIYESI = 7 * 24 * 60 * 60
GECMIS_ORNEK_ARALIGI_SANIYE = 30
UYGULAMA_KULLANIMI_ARALIGI_SANIYE = 10
UYGULAMA_KULLANIMI_MAKS_ARALIK_SANIYE = 20
UYGULAMA_KULLANIMI_SAKLAMA_SANIYESI = 7 * 24 * 60 * 60
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


def uygulamayi_one_getir(uygulama_adi):
    import ctypes
    from ctypes import wintypes

    load_library = getattr(ctypes, "WinDLL", None)
    if load_library is None:
        raise OSError("Uygulama pencerelerini öne getirmek yalnızca Windows'ta desteklenir.")

    user32 = load_library("user32", use_last_error=True)
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_windows_proc, wintypes.LPARAM]
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
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.FlashWindowEx.argtypes = [ctypes.c_void_p]
    user32.FlashWindowEx.restype = wintypes.BOOL

    target_name = uygulama_adi.split(" (")[0].strip().casefold()
    matching_windows = []

    @enum_windows_proc
    def collect_window(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        process_id = wintypes.DWORD()
        if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)):
            return True
        try:
            process_name = Path(psutil.Process(process_id.value).name()).stem.casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        if process_name == target_name:
            matching_windows.append(hwnd)
        return True

    if not user32.EnumWindows(collect_window, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    if not matching_windows:
        raise ValueError(f"'{uygulama_adi}' için görünür bir pencere bulunamadı.")

    window = matching_windows[0]
    user32.ShowWindow(window, 9)
    if not user32.SetForegroundWindow(window):
        class FlashWindowInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        flash_info = FlashWindowInfo(
            ctypes.sizeof(FlashWindowInfo), window, 0x00000002, 3, 0
        )
        user32.FlashWindowEx(ctypes.byref(flash_info))
        return (
            f"Windows '{uygulama_adi}' penceresini öne getirmeye izin vermedi; "
            "dikkatini çekmek için görev çubuğunda yanıp söndürüldü.",
            False,
        )
    return f"'{uygulama_adi}' penceresi öne getirildi.", True


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


def varsayilan_ag_gecidi_kontrol_et():
    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    komut = (
        "$ErrorActionPreference = 'Stop'; "
        "Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' "
        "| Where-Object { $_.NextHop -ne '0.0.0.0' } "
        "| Sort-Object RouteMetric "
        "| Select-Object -First 1 -ExpandProperty NextHop"
    )
    try:
        sonuc = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", komut],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.exception("Varsayılan ağ geçidi okunamadı.")
        return {"gecit": None, "erisilebilir": None, "hata": str(exc)}
    if sonuc.returncode:
        hata = (sonuc.stderr or sonuc.stdout).strip()
        logger.warning("Varsayılan ağ geçidi sorgusu başarısız: %s", hata)
        return {
            "gecit": None,
            "erisilebilir": None,
            "hata": "Varsayılan ağ geçidi okunamadı.",
        }

    gecit = next(
        (satir.strip() for satir in sonuc.stdout.splitlines() if satir.strip()),
        None,
    )
    if gecit is None:
        return {
            "gecit": None,
            "erisilebilir": False,
            "hata": "Etkin varsayılan ağ geçidi bulunamadı.",
        }
    try:
        ipaddress.ip_address(gecit)
    except ValueError:
        logger.error("Windows geçersiz varsayılan ağ geçidi döndürdü: %r", gecit)
        return {
            "gecit": None,
            "erisilebilir": None,
            "hata": "Varsayılan ağ geçidi adresi geçersiz.",
        }

    ping = Path(os.environ["SystemRoot"]) / "System32" / "ping.exe"
    try:
        sonuc = subprocess.run(
            [str(ping), "-n", "1", "-w", "1000", "-4", gecit],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.exception("Varsayılan ağ geçidi yanıtı kontrol edilemedi.")
        return {"gecit": gecit, "erisilebilir": None, "hata": str(exc)}
    return {
        "gecit": gecit,
        "erisilebilir": sonuc.returncode == 0,
        "hata": None,
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


def disk_bilgilerini_topla():
    disks = []
    seen_devices = set()

    for partition in psutil.disk_partitions(all=False):
        device_id = (partition.device or partition.mountpoint).casefold()
        if device_id in seen_devices:
            continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, psutil.Error):
            logger.warning("Disk bilgisi okunamadı: %s", partition.mountpoint, exc_info=True)
            continue
        if usage.total <= 0:
            continue

        seen_devices.add(device_id)
        disks.append(
            {
                "surucu": partition.mountpoint,
                "kullanilan_yuzde": round(usage.percent),
                "bos_gb": round(usage.free / (1024 ** 3), 1),
                "toplam_gb": round(usage.total / (1024 ** 3), 1),
                "toplam_bayt": usage.total,
                "bos_bayt": usage.free,
            }
        )

    total_bytes = sum(disk["toplam_bayt"] for disk in disks)
    free_bytes = sum(disk["bos_bayt"] for disk in disks)
    if not disks:
        logger.error("Kullanılabilir disk bilgisi alınamadı.")
        raise RuntimeError("Kullanılabilir disk bilgisi alınamadı.")

    used_percent = round((total_bytes - free_bytes) / total_bytes * 100)
    return (
        disks,
        used_percent,
        round(free_bytes / (1024 ** 3), 1),
        round(total_bytes / (1024 ** 3), 1),
    )


def _uygulama_kullanim_tablo_hazirla(baglanti):
    baglanti.execute("PRAGMA secure_delete = ON")
    baglanti.execute(
        """
        CREATE TABLE IF NOT EXISTS uygulama_kullanimi (
            id INTEGER PRIMARY KEY,
            uygulama_adi TEXT NOT NULL,
            kayit_zamani REAL NOT NULL,
            saniye INTEGER NOT NULL CHECK (saniye > 0)
        )
        """
    )
    baglanti.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_uygulama_kullanimi_zamani
        ON uygulama_kullanimi (kayit_zamani)
        """
    )


def uygulama_kullanim_gecmisini_temizle():
    saklama_baslangici = time.time() - UYGULAMA_KULLANIMI_SAKLAMA_SANIYESI
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            _uygulama_kullanim_tablo_hazirla(baglanti)
            baglanti.execute(
                "DELETE FROM uygulama_kullanimi WHERE kayit_zamani < ?",
                (saklama_baslangici,),
            )
            baglanti.commit()
    except sqlite3.Error as exc:
        logger.exception("Eski uygulama kullanım kayıtları temizlenemedi.")
        raise RuntimeError("Eski uygulama kullanım kayıtları temizlenemedi.") from exc


def uygulama_kullanimini_kaydet(uygulama_adi, saniye, kayit_zamani=None):
    if not uygulama_adi or saniye <= 0:
        return
    kayit_zamani = time.time() if kayit_zamani is None else kayit_zamani
    saklama_baslangici = kayit_zamani - UYGULAMA_KULLANIMI_SAKLAMA_SANIYESI
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            _uygulama_kullanim_tablo_hazirla(baglanti)
            baglanti.execute(
                """
                INSERT INTO uygulama_kullanimi (uygulama_adi, kayit_zamani, saniye)
                VALUES (?, ?, ?)
                """,
                (uygulama_adi, kayit_zamani, int(saniye)),
            )
            baglanti.execute(
                "DELETE FROM uygulama_kullanimi WHERE kayit_zamani < ?",
                (saklama_baslangici,),
            )
            baglanti.commit()
    except sqlite3.Error as exc:
        logger.exception("Uygulama kullanım süresi yerel veritabanına kaydedilemedi.")
        raise RuntimeError("Uygulama kullanım süresi kaydedilemedi.") from exc


def uygulama_kullanim_ozetini_getir(gun=7):
    if not 1 <= gun <= 7:
        raise ValueError("Uygulama kullanım geçmişi 1 ile 7 gün arasında olmalıdır.")
    simdi = time.time()
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            _uygulama_kullanim_tablo_hazirla(baglanti)
            baglanti.execute(
                "DELETE FROM uygulama_kullanimi WHERE kayit_zamani < ?",
                (simdi - UYGULAMA_KULLANIMI_SAKLAMA_SANIYESI,),
            )
            satirlar = baglanti.execute(
                """
                SELECT uygulama_adi, SUM(saniye) AS toplam_saniye
                FROM uygulama_kullanimi
                WHERE kayit_zamani >= ?
                GROUP BY uygulama_adi
                ORDER BY toplam_saniye DESC, uygulama_adi COLLATE NOCASE
                """,
                (simdi - gun * 24 * 60 * 60,),
            ).fetchall()
            baglanti.commit()
    except sqlite3.Error as exc:
        logger.exception("Uygulama kullanım geçmişi okunamadı.")
        raise RuntimeError("Uygulama kullanım geçmişi okunamadı.") from exc
    return [
        {"ad": uygulama_adi, "saniye": int(toplam_saniye)}
        for uygulama_adi, toplam_saniye in satirlar
    ]


def uygulama_kullanim_gunluk_ozetini_getir(gun=7):
    if not 1 <= gun <= 7:
        raise ValueError("Günlük kullanım geçmişi 1 ile 7 gün arasında olmalıdır.")
    simdi = time.time()
    baslangic = datetime.now().astimezone().date() - timedelta(days=gun - 1)
    gunler = [
        (baslangic + timedelta(days=index)).isoformat()
        for index in range(gun)
    ]
    gunluk = {gun_adi: {} for gun_adi in gunler}
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            _uygulama_kullanim_tablo_hazirla(baglanti)
            baglanti.execute(
                "DELETE FROM uygulama_kullanimi WHERE kayit_zamani < ?",
                (simdi - UYGULAMA_KULLANIMI_SAKLAMA_SANIYESI,),
            )
            satirlar = baglanti.execute(
                """
                SELECT uygulama_adi, kayit_zamani, saniye
                FROM uygulama_kullanimi
                WHERE kayit_zamani >= ?
                """,
                (datetime.combine(baslangic, datetime.min.time()).astimezone().timestamp(),),
            ).fetchall()
            baglanti.commit()
    except sqlite3.Error as exc:
        logger.exception("Günlük uygulama kullanım geçmişi okunamadı.")
        raise RuntimeError("Günlük uygulama kullanım geçmişi okunamadı.") from exc

    for uygulama_adi, kayit_zamani, saniye in satirlar:
        gun_adi = datetime.fromtimestamp(kayit_zamani).astimezone().date().isoformat()
        if gun_adi in gunluk:
            gunluk[gun_adi][uygulama_adi] = (
                gunluk[gun_adi].get(uygulama_adi, 0) + int(saniye)
            )
    return gunluk


def uygulama_kullanim_grafigi_olustur(gun=7):
    gunluk = uygulama_kullanim_gunluk_ozetini_getir(gun)
    toplamlar = {}
    for uygulamalar in gunluk.values():
        for ad, saniye in uygulamalar.items():
            toplamlar[ad] = toplamlar.get(ad, 0) + saniye
    en_cok_kullanan = sorted(
        toplamlar.items(), key=lambda item: (-item[1], item[0].casefold())
    )[:5]
    uygulama_adlari = [ad for ad, _ in en_cok_kullanan]
    diger_toplam = sum(
        saniye for ad, saniye in toplamlar.items() if ad not in uygulama_adlari
    )
    if diger_toplam:
        uygulama_adlari.append("Diğer")

    genislik, yukseklik = 1200, 680
    sol, ust, sag, alt = 100, 110, 1140, 530
    renkler = ("#62a8ff", "#61d6a5", "#ffcb6b", "#c792ea", "#ff7d91", "#77849a")
    cikti_gorseli = Image.new("RGB", (genislik, yukseklik), "#101827")
    cizim = ImageDraw.Draw(cikti_gorseli)
    cizim.text((sol, 28), f"Son {gun} gün • Günlük uygulama kullanımı", fill="#ffffff")
    cizim.text((sol, 62), "Yalnızca aktif pencere süresi • Bugün eksik bir gün olabilir", fill="#aab8ca")

    gun_toplamlari = {
        gun_adi: sum(uygulamalar.values())
        for gun_adi, uygulamalar in gunluk.items()
    }
    en_yuksek = max(gun_toplamlari.values(), default=0)
    skala = max(3600, ((en_yuksek + 3599) // 3600) * 3600)
    bar_grup_genisligi = (sag - sol) / max(1, len(gunluk))
    bar_genisligi = min(74, bar_grup_genisligi * 0.62)
    for saat in range(0, int(skala // 3600) + 1, max(1, int(skala // 3600) // 4)):
        y = alt - (alt - ust) * (saat * 3600) / skala
        cizim.line((sol, y, sag, y), fill="#34445a", width=1)
        cizim.text((24, y - 8), f"{saat} sa", fill="#aab8ca")

    for index, (gun_adi, uygulamalar) in enumerate(gunluk.items()):
        x_merkez = sol + bar_grup_genisligi * (index + 0.5)
        y_alt = alt
        paylar = [uygulamalar.get(ad, 0) for ad in uygulama_adlari if ad != "Diğer"]
        if "Diğer" in uygulama_adlari:
            paylar.append(
                sum(
                    saniye
                    for ad, saniye in uygulamalar.items()
                    if ad not in [item[0] for item in en_cok_kullanan]
                )
            )
        for sira, saniye in enumerate(paylar):
            if saniye <= 0:
                continue
            yukseklik = (alt - ust) * saniye / skala
            cizim.rectangle(
                (
                    x_merkez - bar_genisligi / 2,
                    y_alt - yukseklik,
                    x_merkez + bar_genisligi / 2,
                    y_alt,
                ),
                fill=renkler[sira % len(renkler)],
            )
            y_alt -= yukseklik
        cizim.text((x_merkez - 30, alt + 14), date.fromisoformat(gun_adi).strftime("%d.%m"), fill="#aab8ca")

    for index, ad in enumerate(uygulama_adlari):
        x = sol + (index % 3) * 330
        y = 610 + (index // 3) * 24
        cizim.rectangle((x, y, x + 16, y + 16), fill=renkler[index % len(renkler)])
        cizim.text((x + 24, y + 2), ad[:32], fill="#ffffff")
    cikti = io.BytesIO()
    cikti_gorseli.save(cikti, format="PNG", optimize=True)
    cikti.seek(0)
    return cikti


def baslangic_uygulamalarini_topla():
    import winreg

    uygulamalar = set()
    kayit_yollari = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
        ),
    )
    for kok, alt_yol in kayit_yollari:
        try:
            with winreg.OpenKey(kok, alt_yol) as anahtar:
                index = 0
                while True:
                    try:
                        ad, _, _ = winreg.EnumValue(anahtar, index)
                    except OSError:
                        break
                    if ad.strip():
                        uygulamalar.add(ad.strip())
                    index += 1
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("Windows başlangıç kayıtları okunamadı: %s", alt_yol)

    baslangic_dizinleri = [
        Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        for base in (
            os.environ.get("APPDATA"),
            os.environ.get("PROGRAMDATA"),
        )
        if base
    ]
    for dizin in baslangic_dizinleri:
        try:
            for yol in dizin.iterdir():
                if yol.is_file() and yol.suffix.casefold() in (".lnk", ".url", ".exe"):
                    uygulamalar.add(yol.stem)
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("Windows başlangıç klasörü okunamadı: %s", dizin)
    return sorted(uygulamalar, key=str.casefold)


def sicakliklari_topla():
    oku = getattr(psutil, "sensors_temperatures", None)
    if oku is None:
        logger.info("Sıcaklık sensörleri bu sistemde kullanılamıyor.")
        return []
    try:
        sicaklik_sensorleri = oku(fahrenheit=False)
    except (AttributeError, NotImplementedError, OSError, psutil.Error):
        logger.info("Sıcaklık sensörleri bu sistemde kullanılamıyor.")
        return []
    if not sicaklik_sensorleri:
        return []
    sicakliklar = []
    for sensor_adi, okumalar in sicaklik_sensorleri.items():
        for okuma in okumalar:
            if okuma.current is None:
                continue
            etiket = okuma.label.strip() if okuma.label else sensor_adi
            sicakliklar.append(
                {
                    "etiket": etiket[:32],
                    "celsius": round(float(okuma.current)),
                    "kategori": sensor_adi.casefold(),
                }
            )
    return sicakliklar


def uygulama_kullanim_gecmisini_sil():
    try:
        with closing(sqlite3.connect(GECMIS_DOSYASI, timeout=5)) as baglanti:
            _uygulama_kullanim_tablo_hazirla(baglanti)
            baglanti.execute("DELETE FROM uygulama_kullanimi")
            baglanti.commit()
    except sqlite3.Error as exc:
        logger.exception("Uygulama kullanım geçmişi silinemedi.")
        raise RuntimeError("Uygulama kullanım geçmişi silinemedi.") from exc


def uygulama_kullanim_takibini_ayarla(acik):
    try:
        with AYAR_DOSYASI.open("r", encoding="utf-8") as ayar_dosyasi:
            ayarlar = json.load(ayar_dosyasi)
        if not isinstance(ayarlar, dict):
            raise ValueError("Uygulama ayar dosyasının biçimi geçersiz.")
        ayarlar["TRACK_APP_USAGE"] = bool(acik)
        gecici_yol = AYAR_DOSYASI.with_suffix(".json.tmp")
        gecici_yol.write_text(
            json.dumps(ayarlar, indent=2),
            encoding="utf-8",
        )
        os.replace(gecici_yol, AYAR_DOSYASI)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.exception("Uygulama kullanım takibi ayarı kaydedilemedi.")
        raise RuntimeError("Uygulama kullanım takibi ayarı kaydedilemedi.") from exc


def aktif_pencere_uygulamasini_getir():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
    user32.GetLastInputInfo.restype = wintypes.BOOL
    kernel32.GetTickCount.argtypes = []
    kernel32.GetTickCount.restype = wintypes.DWORD

    input_info = LastInputInfo()
    input_info.cbSize = ctypes.sizeof(input_info)
    if not user32.GetLastInputInfo(ctypes.byref(input_info)):
        raise ctypes.WinError(ctypes.get_last_error())
    idle_milliseconds = (
        kernel32.GetTickCount() - input_info.dwTime
    ) & 0xFFFFFFFF
    if idle_milliseconds > 5 * 60 * 1000:
        return None

    foreground_window = user32.GetForegroundWindow()
    if not foreground_window:
        return None
    process_id = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(
        foreground_window, ctypes.byref(process_id)
    ):
        return None
    if process_id.value == os.getpid():
        return None

    try:
        process_name = psutil.Process(process_id.value).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    return Path(process_name).stem or None


def uygulama_kullanimini_izle():
    try:
        with AYAR_DOSYASI.open("r", encoding="utf-8") as ayar_dosyasi:
            ayarlar = json.load(ayar_dosyasi)
    except (OSError, json.JSONDecodeError):
        logger.exception("Uygulama kullanım ayarları okunamadı; izleme başlatılmadı.")
        return
    if not isinstance(ayarlar, dict):
        logger.error("Uygulama kullanım ayar dosyasının biçimi geçersiz.")
        return

    try:
        uygulama_kullanim_gecmisini_temizle()
    except RuntimeError:
        return
    onceki_uygulama = None
    onceki_zaman = None
    sonraki_temizleme_zamani = time.monotonic() + 60 * 60
    logger.info("Aktif pencere uygulama süre izleyicisi hazır.")
    while not kapatma_olayi.is_set():
        try:
            with AYAR_DOSYASI.open("r", encoding="utf-8") as ayar_dosyasi:
                ayarlar = json.load(ayar_dosyasi)
            if not isinstance(ayarlar, dict):
                raise ValueError("Uygulama ayar dosyasının biçimi geçersiz.")
            if ayarlar.get("TRACK_APP_USAGE") is not True:
                onceki_uygulama = None
                onceki_zaman = None
                simdi = time.monotonic()
                if simdi >= sonraki_temizleme_zamani:
                    sonraki_temizleme_zamani = simdi + 60 * 60
                    uygulama_kullanim_gecmisini_temizle()
                kapatma_olayi.wait(UYGULAMA_KULLANIMI_ARALIGI_SANIYE)
                continue

            uygulama = aktif_pencere_uygulamasini_getir()
            simdi = time.monotonic()
            if simdi >= sonraki_temizleme_zamani:
                sonraki_temizleme_zamani = simdi + 60 * 60
                uygulama_kullanim_gecmisini_temizle()
            if (
                uygulama
                and uygulama == onceki_uygulama
                and onceki_zaman is not None
            ):
                gecen_saniye = min(
                    int(simdi - onceki_zaman),
                    UYGULAMA_KULLANIMI_MAKS_ARALIK_SANIYE,
                )
                if gecen_saniye > 0:
                    uygulama_kullanimini_kaydet(uygulama, gecen_saniye)
            onceki_uygulama = uygulama
            onceki_zaman = simdi if uygulama else None
        except (OSError, psutil.Error, RuntimeError, ValueError):
            logger.exception("Aktif pencere kullanımı ölçülemedi.")
            onceki_uygulama = None
            onceki_zaman = None
        kapatma_olayi.wait(UYGULAMA_KULLANIMI_ARALIGI_SANIYE)


def durum_topla(kaydet_gecmis=True):
    global bekleyen_guc_islemi, bekleyen_islem_bitis_zamani
    try:
        cpu = round(psutil.cpu_percent(interval=None))
        memory = round(psutil.virtual_memory().percent)
        disks, disk_percent, disk_free_gb, disk_total_gb = disk_bilgilerini_topla()
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
        ag_gecidi = varsayilan_ag_gecidi_kontrol_et()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.exception("Varsayılan ağ geçidi durumu toplanamadı.")
        ag_gecidi = {
            "gecit": None,
            "erisilebilir": None,
            "hata": "Ağ geçidi durumu okunamadı.",
        }
    sicakliklar = sicakliklari_topla()
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

    if kaydet_gecmis:
        history_error = gecmisi_kaydet(cpu, memory, disk_percent)
    else:
        history_error = None
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
        "disk_kullanilan_yuzde": disk_percent,
        "disk_bos_gb": disk_free_gb,
        "disk_toplam_gb": disk_total_gb,
        "disk_suruculer": disks,
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
        "ag_gecidi": ag_gecidi,
        "sicakliklar": sicakliklar,
        "uygulama_takibi_acik": uygulama_takibini_durumdan_oku(),
        "gecmis_hatasi": history_error,
        "bekleyen_islem": current_action,
        "bekleyen_islem_saniye": pending_seconds,
    }


def uygulama_takibini_durumdan_oku():
    try:
        with AYAR_DOSYASI.open("r", encoding="utf-8") as ayar_dosyasi:
            ayarlar = json.load(ayar_dosyasi)
    except (OSError, json.JSONDecodeError):
        logger.exception("Uygulama kullanım takibi ayarı okunamadı.")
        return False
    return isinstance(ayarlar, dict) and ayarlar.get("TRACK_APP_USAGE") is True


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


def guc_islemi_yurut(islem, gecikme_saniye=60):
    global bekleyen_guc_islemi, bekleyen_islem_bitis_zamani
    shutdown_exe = Path(os.environ["SystemRoot"]) / "System32" / "shutdown.exe"
    if not shutdown_exe.is_file():
        raise OSError("Windows shutdown.exe bulunamadı.")

    if islem in ("restart", "shutdown") and (
        type(gecikme_saniye) is not int
        or not 60 <= gecikme_saniye <= 7 * 24 * 60 * 60
    ):
        raise ValueError("Güç işlemi gecikmesi 60 saniye ile 7 gün arasında olmalıdır.")

    with ISLEM_KILIDI:
        if islem in ("restart", "shutdown"):
            if bekleyen_guc_islemi:
                raise ValueError("Zaten planlanmış bir güç işlemi var; önce iptal et.")
            command = [
                str(shutdown_exe),
                "/r" if islem == "restart" else "/s",
                "/t",
                str(gecikme_saniye),
                "/c",
                "Yetkili Discord kontrol panelinden planlandı",
            ]
            gecikme_metni = sureyi_bicimlendir(gecikme_saniye)
            message = (
                f"Yeniden başlatma {gecikme_metni} sonrasına planlandı."
                if islem == "restart"
                else f"Bilgisayarın kapanması {gecikme_metni} sonrasına planlandı."
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
            bekleyen_islem_bitis_zamani = time.time() + gecikme_saniye
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

    threading.Thread(
        target=uygulama_kullanimini_izle,
        name="aktif-uygulama-kullanim-izleyicisi",
        daemon=True,
    ).start()
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