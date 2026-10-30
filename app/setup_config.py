import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


APP_NAME = "PCActivityMonitor"
CONSENT_VERSION = "2026-10-29-discord-control-app-list"


def read_hidden_input(prompt):
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return simpledialog.askstring(
            "Discord bot token",
            f"{prompt}\nYapıştırmak için Ctrl+V kullanabilirsin.",
            show="*",
            parent=root,
        )
    finally:
        root.destroy()


def ask_bot_token():
    while True:
        token = read_hidden_input("Discord bot token")
        if token is None:
            print("Kurulum iptal edildi; yeni yapılandırma kaydedilmedi.")
            raise SystemExit(1)
        token = token.strip()
        if token and not any(character.isspace() for character in token):
            return token
        print("Geçerli, boşluk içermeyen bot token'ı gir.")


def ask_discord_id(prompt):
    while True:
        value = input(prompt).strip()
        if value.isdecimal() and int(value) > 0:
            return int(value)
        print("Pozitif sayısal Discord ID'si gir.")


def build_config(bot_token, allowed_user_id, guild_id, channel_id):
    return {
        "BOT_TOKEN": bot_token,
        "ALLOWED_USER_ID": allowed_user_id,
        "GUILD_ID": guild_id,
        "CHANNEL_ID": channel_id,
        "CONSENT": {
            "notice_version": CONSENT_VERSION,
            "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }


def save_config(config):
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("Windows APPDATA klasörü bulunamadı.")
    state_dir = Path(app_data) / APP_NAME
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


def load_existing_config():
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("Windows APPDATA klasörü bulunamadı.")
    config_path = Path(app_data) / APP_NAME / "config.json"
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


def confirm_privacy_notice(config, reuse_existing):
    if reuse_existing:
        print("\nKAYITLI AYARLAR")
        print("- Discord bot token'ı ve kullanıcı/sunucu/kanal ID'leri korunacak.")
        print(f"- İzinli Discord kullanıcı ID'si: {config['ALLOWED_USER_ID']}")
        print(f"- Discord sunucu ID'si: {config['GUILD_ID']}")
        print(f"- Özel kontrol kanalı ID'si: {config['CHANNEL_ID']}")
    else:
        print("\nKURULUM ÖZETİ")
        print(f"- İzinli Discord kullanıcı ID'si: {config['ALLOWED_USER_ID']}")
        print(f"- Kontrol panelinin bulunduğu Discord sunucusu ID'si: {config['GUILD_ID']}")
        print(f"- Butonlu PC kontrol Embed'inin gönderileceği özel kanal ID'si: {config['CHANNEL_ID']}")
        print("- Yalnızca Discord üzerinden kontrol kullanılacaktır; yerel web paneli kurulmaz.")

    print("- Discord Embed altında durum, açık uygulamalar, ekran görüntüsü ve güç kontrolleri.")
    print("- Sistem bilgileri ve görünür penceresi olan uygulama adları Discord'a gönderilir.")
    print("- Uygulama adları gösterilir; pencere başlıkları ve içerikleri alınmaz.")
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


def reuse_existing_config():
    config = load_existing_config()
    if not confirm_privacy_notice(config, reuse_existing=True):
        return 1
    for key in ("PORT", "ACCESS_PASSWORD_HASH", "SERVICE_KEY"):
        config.pop(key, None)
    config["CONSENT"] = {
        "notice_version": CONSENT_VERSION,
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    config_path = save_config(config)
    print(f"\nKayıtlı Discord ve erişim ayarları korundu: {config_path}")
    print("Token ve ID'ler yeniden sorulmadı.")
    return 0


def set_pythonw_path(path):
    pythonw_path = Path(path)
    if not pythonw_path.is_file():
        raise FileNotFoundError(f"pythonw.exe bulunamadı: {pythonw_path}")
    app_data = os.environ.get("APPDATA")
    if not app_data:
        raise RuntimeError("Windows APPDATA klasörü bulunamadı.")
    state_dir = Path(app_data) / APP_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "pythonw_path.txt").write_text(str(pythonw_path), encoding="utf-16")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-pythonw-path")
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Reuse saved credentials and IDs and renew the privacy consent.",
    )
    args = parser.parse_args()
    if args.set_pythonw_path:
        set_pythonw_path(args.set_pythonw_path)
        return 0
    if args.reuse_existing:
        return reuse_existing_config()

    print("=" * 68)
    print("DISCORD PC KONTROL BOTU - KİŞİSEL KURULUM")
    print("=" * 68)
    print("Önce Discord Developer Portal'da kendi bot uygulamanı oluştur.")
    print("Botu kullanacağın sunucuya ekle ve özel kontrol kanalına izin ver.")
    print("Bot token'ı girişte gizlenir; kendi Discord kullanıcı ID'ni izin listesine al.")
    print("Discord Developer Mode ile kullanıcı ve sunucu ID'lerini kopyalayabilirsin.")
    bot_token = ask_bot_token()
    allowed_user_id = ask_discord_id("Kendi Discord kullanıcı ID'n: ")
    guild_id = ask_discord_id("Botu eklediğin Discord sunucusunun ID'si: ")
    channel_id = ask_discord_id("Özel PC kontrol kanalının ID'si: ")
    config = build_config(
        bot_token,
        allowed_user_id,
        guild_id,
        channel_id,
    )
    if not confirm_privacy_notice(config, reuse_existing=False):
        return 1

    config_path = save_config(config)

    print(f"\nYapılandırma kaydedildi: {config_path}")
    print("Discord kontrol botu ayarları kaydedildi.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Kurulum hatası: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
