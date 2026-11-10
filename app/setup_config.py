import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


UYGULAMA_ADI = "PCActivityMonitor"
ONAY_SURUMU = "2026-11-10-reminders-and-controls"


def gizli_girdiyi_oku(metin):
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return simpledialog.askstring(
            "Discord bot token'ı",
            f"{metin}\nYapıştırmak için Ctrl+V kullanabilirsin.",
            show="*",
            parent=root,
        )
    finally:
        root.destroy()


def bot_tokeni_iste():
    while True:
        token = gizli_girdiyi_oku("Discord bot token'ı")
        if token is None:
            print("Kurulum iptal edildi; yeni yapılandırma kaydedilmedi.")
            raise SystemExit(1)
        token = token.strip()
        if token and not any(character.isspace() for character in token):
            return token
        print("Geçerli, boşluk içermeyen bot token'ı gir.")


def discord_kimligini_iste(metin):
    while True:
        value = input(metin).strip()
        if value.isdecimal() and int(value) > 0:
            return int(value)
        print("Pozitif sayısal Discord ID'si gir.")


def ayarlari_olustur(bot_anahtari, izinli_kullanici_kimligi, sunucu_kimligi, kanal_kimligi):
    return {
        "BOT_TOKEN": bot_anahtari,
        "ALLOWED_USER_ID": izinli_kullanici_kimligi,
        "GUILD_ID": sunucu_kimligi,
        "CHANNEL_ID": kanal_kimligi,
        "TRACK_APP_USAGE": False,
        "CONSENT": {
            "notice_version": ONAY_SURUMU,
            "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }


def ayarlari_kaydet(config):
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("Windows APPDATA klasörü bulunamadı.")
    state_dir = Path(app_data) / UYGULAMA_ADI
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    temp_config = config_path.with_suffix(".json.tmp")
    try:
        temp_config.write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_config, config_path)
    except OSError:
        temp_config.unlink(missing_ok=True)
        raise
    return config_path


def mevcut_ayarlari_yukle():
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("Windows APPDATA klasörü bulunamadı.")
    config_path = Path(app_data) / UYGULAMA_ADI / "config.json"
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("Kayıtlı ayar dosyasının biçimi geçersiz.")

    bot_token = config.get("BOT_TOKEN")
    user_id = int(config.get("ALLOWED_USER_ID", 0))
    guild_id = int(config.get("GUILD_ID", 0))
    channel_id = int(config.get("CHANNEL_ID", 0))
    if (
        not isinstance(bot_token, str)
        or not bot_token
        or any(character.isspace() for character in bot_token)
        or min(user_id, guild_id, channel_id) <= 0
    ):
        raise ValueError(
            "Kayıtlı ayarlar eksik veya geçersiz. Yeni ayarlarla devam et."
        )
    return config


def uygulama_kullanim_takibini_iste(ayarlar):
    varsayilan = ayarlar.get("TRACK_APP_USAGE") is True
    varsayilan_metni = "E" if varsayilan else "H"
    while True:
        yanit = input(
            "Aktif pencere uygulamalarının yaklaşık kullanım süresini izle? "
            f"(E/H, varsayılan {varsayilan_metni}): "
        ).strip().casefold()
        if not yanit:
            secim = varsayilan
            break
        if yanit in ("e", "evet", "y", "yes"):
            secim = True
            break
        if yanit in ("h", "hayır", "hayir", "n", "no"):
            secim = False
            break
        print("Evet için E, hayır için H gir.")
    ayarlar["TRACK_APP_USAGE"] = secim
    return secim


def gizlilik_bildirimini_onayla(ayarlar, kayitli_ayarlari_kullan):
    if kayitli_ayarlari_kullan:
        print("\nKAYITLI AYARLAR")
        print("- Discord bot token'ı ve kullanıcı/sunucu/kanal ID'leri korunacak.")
        print(f"- İzinli Discord kullanıcı ID'si: {ayarlar['ALLOWED_USER_ID']}")
        print(f"- Discord sunucu ID'si: {ayarlar['GUILD_ID']}")
        print(f"- Özel kontrol kanalı ID'si: {ayarlar['CHANNEL_ID']}")
    else:
        print("\nKURULUM ÖZETİ")
        print(f"- İzinli Discord kullanıcı ID'si: {ayarlar['ALLOWED_USER_ID']}")
        print(f"- Kontrol panelinin bulunduğu Discord sunucusu ID'si: {ayarlar['GUILD_ID']}")
        print(f"- Butonlu PC kontrol Embed'inin gönderileceği özel kanal ID'si: {ayarlar['CHANNEL_ID']}")
        print("- Yalnızca Discord üzerinden kontrol kullanılacaktır; yerel web paneli kurulmaz.")

    print("- Discord panelinde sistem durumu, süreç özeti, ağ trafiği ve bilgisayar kontrolleri gösterilir.")
    print("- Sistem bilgileri, görünür uygulama adları ve en çok kaynak kullanan süreç adları Discord'a gönderilir.")
    print("- Ağ geçidi adresi kontrol panelinde gösterilir ve yalnızca ağ geçidine ping atılır; genel internete ping gönderilmez.")
    print("- Başlangıç uygulamaları yalnızca istendiğinde özel yanıtla listelenir; hiçbir ayar değiştirilmez.")
    print("- Destekleniyorsa donanım sıcaklıkları ve işlemci/bellek/disk kullanım yüzdeleri panelde gösterilir.")
    print("- Kaynak eşiklerinde Discord uyarısı gönderilmez; renkler yalnızca anlık değerleri belirtir.")
    print("- CPU, bellek ve disk geçmişi yerel veritabanında en fazla 7 gün saklanır.")
    print("- Geçmiş grafikleri yalnızca istediğinde Discord'a özel yanıt olarak gönderilir.")
    print("- Uygulama adları gösterilir; pencere başlıkları ve içerikleri alınmaz.")
    print("- Seçilen görünür uygulama penceresi öne getirilebilir; pencere başlığı okunmaz.")
    print("- Hatırlatıcı notları yerel olarak saklanır; zamanı geldiğinde bu bilgisayarda sesli uyarı penceresi açılır, Discord'a bildirim gönderilmez.")
    print("- Yeniden başlatma veya kapatma 1 dakika ile 7 gün arasında zamanlanabilir; onay ve iptal gerekir.")
    uygulama_takibi_acik = uygulama_kullanim_takibini_iste(ayarlar)
    if uygulama_takibi_acik:
        print("- Aktif pencerenin uygulama adı ve yaklaşık süresi yerel olarak 7 gün saklanır.")
        print("- 5 dakikadan uzun boşta kalma süresi sayılmaz; uygulama adları Discord'a otomatik gönderilmez.")
        print("- Son 7 gün özeti yalnızca Discord'daki özel kullanım düğmesine bastığında gönderilir.")
    else:
        print("- Aktif pencere uygulama kullanım süresi takibi kapalıdır.")
    print("- Ekran görüntüsü yalnızca düğmeye bastığında Discord servisine gönderilir.")
    print("- Discord, ekran görüntüsü dosyasını ve etkileşimleri kendi hizmetinde işleyebilir.")
    print("- Bot token'ı yerel ayar dosyasında saklanır; dosyayı veya token'ı paylaşma.")
    print("\nBu bilgisayarın kullanıcısı olarak bildirimi okuyup kabul ediyorsan")
    print('aynen "KABUL EDİYORUM" yaz. Vazgeçmek için Q yaz.')
    answer = input("> ").strip().upper()
    if answer == "Q":
        print("Kurulum iptal edildi; yeni yapılandırma kaydedilmedi.")
        return False
    if answer != "KABUL EDİYORUM":
        print('Kurulum iptal edildi. Tam olarak "KABUL EDİYORUM" yazılmalı.')
        return False
    return True


def mevcut_ayarlari_kullan():
    config = mevcut_ayarlari_yukle()
    if not gizlilik_bildirimini_onayla(config, kayitli_ayarlari_kullan=True):
        return 1
    for key in ("PORT", "ACCESS_PASSWORD_HASH", "SERVICE_KEY"):
        config.pop(key, None)
    config["CONSENT"] = {
        "notice_version": ONAY_SURUMU,
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    config_path = ayarlari_kaydet(config)
    print(f"\nKayıtlı Discord ve erişim ayarları korundu: {config_path}")
    print("Token ve ID'ler yeniden sorulmadı.")
    return 0


def pythonw_yolunu_kaydet(yol):
    pythonw_path = Path(yol)
    if not pythonw_path.is_file():
        raise FileNotFoundError(f"pythonw.exe bulunamadı: {pythonw_path}")
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("Windows APPDATA klasörü bulunamadı.")
    state_dir = Path(app_data) / UYGULAMA_ADI
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "pythonw_path.txt").write_text(str(pythonw_path), encoding="utf-16")


def ana():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-pythonw-path")
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Kayıtlı token ve ID'leri korur, gizlilik onayını yeniler.",
    )
    args = parser.parse_args()
    if args.set_pythonw_path:
        pythonw_yolunu_kaydet(args.set_pythonw_path)
        return 0
    if args.reuse_existing:
        return mevcut_ayarlari_kullan()

    print("=" * 68)
    print("DISCORD PC KONTROL BOTU - KİŞİSEL KURULUM")
    print("=" * 68)
    print("Önce Discord Developer Portal'da kendi bot uygulamanı oluştur.")
    print("Botu kullanacağın sunucuya ekle ve özel kontrol kanalına izin ver.")
    print("Bot token'ı girişte gizlenir; kendi Discord kullanıcı ID'ni izin listesine al.")
    print("Discord Developer Mode ile kullanıcı ve sunucu ID'lerini kopyalayabilirsin.")
    bot_token = bot_tokeni_iste()
    allowed_user_id = discord_kimligini_iste("Kendi Discord kullanıcı ID'n: ")
    guild_id = discord_kimligini_iste("Botu eklediğin Discord sunucusunun ID'si: ")
    channel_id = discord_kimligini_iste("Özel PC kontrol kanalının ID'si: ")
    config = ayarlari_olustur(
        bot_token,
        allowed_user_id,
        guild_id,
        channel_id,
    )
    if not gizlilik_bildirimini_onayla(config, kayitli_ayarlari_kullan=False):
        return 1

    config_path = ayarlari_kaydet(config)

    print(f"\nYapılandırma kaydedildi: {config_path}")
    print("Discord kontrol botu ayarları kaydedildi.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(ana())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Kurulum hatası: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
