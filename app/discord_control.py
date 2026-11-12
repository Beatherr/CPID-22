import asyncio
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time
import uuid

import discord
from discord import app_commands

import client as pc
from reminders import hatirlatici_zamani_olustur, masaustu_bildirimi_goster
from system_health import sistem_sagligi_ozetini_olustur


UYGULAMA_ADI = "PCActivityMonitor"
DURUM_DIZINI = Path(os.environ["APPDATA"]) / UYGULAMA_ADI
AYAR_DOSYASI = DURUM_DIZINI / "config.json"
PANEL_DOSYASI = DURUM_DIZINI / "discord_panel.json"
HAZIRLIK_DOSYASI = DURUM_DIZINI / "discord_ready.json"
HATIRLATICI_DOSYASI = DURUM_DIZINI / "reminders.json"
GUNLUK_DOSYASI = DURUM_DIZINI / "discord.log"
logger = logging.getLogger("pc_discord_control")
logger.setLevel(logging.INFO)
logger.addHandler(
    RotatingFileHandler(GUNLUK_DOSYASI, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
)

with AYAR_DOSYASI.open("r", encoding="utf-8") as ayar_dosyasi:
    ayarlar = json.load(ayar_dosyasi)

bot_anahtari = ayarlar.get("BOT_TOKEN")
yetkili_kullanici_kimligi = int(ayarlar.get("ALLOWED_USER_ID", 0))
sunucu_kimligi = int(ayarlar.get("GUILD_ID", 0))
kontrol_kanali_kimligi = int(ayarlar.get("CHANNEL_ID", 0))
uygulama_kullanim_takibi_acik = ayarlar.get("TRACK_APP_USAGE") is True
bot_olay_dongusu = None
discord_istemcisi = None
baslangic_hatasi = None


def kullanima_yetkili_mi(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.id == yetkili_kullanici_kimligi
        and interaction.guild_id == sunucu_kimligi
        and interaction.channel_id == kontrol_kanali_kimligi
    )


def renkli_yuk_cubugu(yuzde, genislik=10):
    deger = max(0, min(100, int(yuzde)))
    dolu = min(genislik, round(deger / 100 * genislik))
    renk = "🟩" if deger < 60 else "🟨" if deger < 80 else "🟧" if deger < 90 else "🟥"
    return f"{renk * dolu}{'⬛' * (genislik - dolu)}"


def durum_rengi(status):
    health = sistem_sagligi_ozetini_olustur(status)
    if health["durum"] == "Kritik":
        return discord.Color.red()
    if health["durum"] == "Dikkat":
        return discord.Color.orange()

    en_yuksek = max(
        status["cpu"],
        status["bellek_yuzde"],
        status["disk_kullanilan_yuzde"],
    )
    if en_yuksek >= 90:
        return discord.Color.red()
    if en_yuksek >= 80:
        return discord.Color.orange()
    if en_yuksek >= 60:
        return discord.Color.gold()
    return discord.Color.green()


def durum_gomulusu_olustur(status=None):
    status = status or pc.durum_topla()
    now = datetime.now().astimezone()
    pending = status["bekleyen_islem"]
    if pending == "restart":
        power_state = f"Yeniden başlatma planlandı · {status['bekleyen_islem_saniye']} sn kaldı"
    elif pending == "shutdown":
        power_state = f"Kapatma planlandı · {status['bekleyen_islem_saniye']} sn kaldı"
    else:
        power_state = "Planlanmış işlem yok"

    embed = discord.Embed(
        title="🖥️ Kişisel PC Kontrol Merkezi",
        description=(
            "Canlı sistem özeti • Kaynak uyarıları yalnızca panelde gösterilir\n"
            "🟩 Normal  🟨 Orta  🟧 Yüksek  🟥 Çok yüksek"
        ),
        color=durum_rengi(status),
        timestamp=now,
    )
    embed.set_author(name=f"{status['bilgisayar_adi']} • PCActivityMonitor")
    health = sistem_sagligi_ozetini_olustur(status)
    health_summary = f"**{health['emoji']} {health['durum']}**"
    if health["uyarilar"]:
        health_summary += f" · {health['uyarilar'][0]}"
    else:
        health_summary += " · Güncel değerlerde yüksek kaynak kullanımı yok."
    embed.add_field(name="🩺 Sistem sağlığı", value=health_summary, inline=False)
    embed.add_field(
        name="💻 Bilgisayar",
        value=(
            f"**Ad:** `{status['bilgisayar_adi']}`\n"
            f"**Windows hesabı:** `{status['kullanici_adi']}`\n"
            f"**Çalışma süresi:** {pc.sureyi_bicimlendir(status['calisma_suresi_saniye'])}\n"
            f"**Uygulama takibi:** {'Açık' if status['uygulama_takibi_acik'] else 'Kapalı'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚙️ İşlemci",
        value=(
            f"{renkli_yuk_cubugu(status['cpu'])} **{status['cpu']}%**\n"
            f"**Model:** {status['cpu_modeli']}\n"
            f"**Çekirdek / izlek:** {status['cpu_cekirdek']} / {status['cpu_izlek']}\n"
            f"**Anlık frekans:** {status['cpu_frekans_mhz'] or 'Yok'} MHz"
        ),
        inline=True,
    )
    embed.add_field(
        name="🧠 Bellek",
        value=(
            f"{renkli_yuk_cubugu(status['bellek_yuzde'])} **{status['bellek_yuzde']}%**\n"
            f"({status['bellek_kullanilan_gb']} / {status['bellek_toplam_gb']} GB)\n"
            f"**Kullanılabilir:** {status['bellek_kullanilabilir_gb']} GB"
        ),
        inline=True,
    )
    disk_header = (
        f"**Toplam kullanım:** {status['disk_kullanilan_yuzde']}%\n"
        f"**Boş / toplam:** {status['disk_bos_gb']} / {status['disk_toplam_gb']} GB"
    )
    disk_lines = [
        f"{renkli_yuk_cubugu(disk['kullanilan_yuzde'], 6)} `{disk['surucu']}` "
        f"**{disk['kullanilan_yuzde']}%** · "
        f"{disk['bos_gb']} / {disk['toplam_gb']} GB boş"
        for disk in status["disk_suruculer"]
    ]
    visible_disk_lines = []
    for index, line in enumerate(disk_lines):
        omitted_count = len(disk_lines) - index - 1
        omitted_note = f"\n• ... ve {omitted_count} disk daha" if omitted_count else ""
        candidate = "\n".join([disk_header, *visible_disk_lines, line]) + omitted_note
        if len(candidate) > 1024:
            visible_disk_lines.append(f"• ... ve {len(disk_lines) - index} disk daha")
            break
        visible_disk_lines.append(line)
    embed.add_field(
        name="💽 Diskler (toplam)",
        value="\n".join([disk_header, *visible_disk_lines]),
        inline=True,
    )
    embed.add_field(
        name="⏱️ Sistem",
        value=(
            f"**Çalışma süresi:** {pc.sureyi_bicimlendir(status['calisma_suresi_saniye'])}\n"
            f"**Son açılış:** {status['baslangic_zamani']}\n"
            f"**İşletim sistemi:** {status['isletim_sistemi']}"
        ),
        inline=True,
    )
    embed.add_field(
        name="🔋 Pil",
        value=status["pil_durumu"],
        inline=True,
    )
    ag = status["ag"]
    ag_gecidi = status["ag_gecidi"]
    if ag is None:
        ag_metni = status["ag_hatasi"] or "Ağ bilgisi kullanılamıyor."
    else:
        gonderim = (
            "hesaplanıyor"
            if ag["gonderim_hizi"] is None
            else f"{pc.boyutu_bicimlendir(ag['gonderim_hizi'])}/sn"
        )
        alim = (
            "hesaplanıyor"
            if ag["alim_hizi"] is None
            else f"{pc.boyutu_bicimlendir(ag['alim_hizi'])}/sn"
        )
        ag_metni = (
            f"**Bağlı ağ arayüzü:** {ag['etkin_arayuz_sayisi']}\n"
            f"**Anlık:** ↑ {gonderim} · ↓ {alim}\n"
            f"**Windows açılışından beri:** ↑ {pc.boyutu_bicimlendir(ag['gonderilen_bayt'])} "
            f"· ↓ {pc.boyutu_bicimlendir(ag['alinan_bayt'])}"
        )
    if ag_gecidi["gecit"]:
        if ag_gecidi["erisilebilir"] is True:
            gateway_status = "🟩 yanıtlıyor"
        elif ag_gecidi["erisilebilir"] is False:
            gateway_status = "🟨 ping yanıtı yok"
        else:
            gateway_status = "⬜ kontrol edilemedi"
        ag_metni += (
            f"\n**Ağ geçidi:** `{ag_gecidi['gecit']}` "
            f"{gateway_status}"
        )
    elif ag_gecidi["hata"]:
        ag_metni += f"\n**Ağ geçidi:** {ag_gecidi['hata']}"
    embed.add_field(name="🌐 Ağ trafiği", value=ag_metni, inline=True)

    sicakliklar = status["sicakliklar"]
    if sicakliklar:
        sicaklik_metni = "\n".join(
            f"{'🟩' if sensor['celsius'] < 70 else '🟨' if sensor['celsius'] < 85 else '🟥'} "
            f"`{sensor['etiket']}` — **{sensor['celsius']}°C**"
            for sensor in sicakliklar[:6]
        )
    else:
        sicaklik_metni = "Bu bilgisayar sıcaklık sensörü verisi sağlamıyor."
    embed.add_field(name="🌡️ Donanım sıcaklığı", value=sicaklik_metni, inline=True)

    surecler = status["en_cok_kullanan_surecler"]
    if status["surec_hatasi"]:
        surec_metni = status["surec_hatasi"]
    elif surecler:
        surec_metni = "\n".join(
            f"• `{surec['ad'][:32]}` — {surec['bellek_mb']} MB RAM "
            f"({surec['bellek_yuzde']}%) · {surec['cpu']}% CPU"
            for surec in surecler
        )
    else:
        surec_metni = "Kaynak kullanan süreç bulunamadı."
    embed.add_field(name="📊 En çok kaynak kullanan süreçler", value=surec_metni, inline=True)
    applications = status["acik_uygulamalar"]
    application_lines = applications[:10]
    embed.add_field(
        name=f"🪟 Açık uygulamalar ({len(applications)})",
        value="\n".join([f"• `{name[:48]}`" for name in application_lines])
        if application_lines
        else "Görünür uygulama penceresi bulunamadı.",
        inline=True,
    )
    embed.add_field(name="🔌 Güç durumu", value=power_state, inline=False)
    embed.set_footer(
        text=(
            f"PC Kontrol • Son güncelleme: {now.strftime('%d.%m.%Y %H:%M:%S')} "
            "• Otomatik yenileme: 60 sn"
        )
    )
    return embed


def hata_gomulusu_olustur(title, message):
    return discord.Embed(
        title=title,
        description=message,
        color=discord.Color.red(),
        timestamp=datetime.now().astimezone(),
    )


def hatirlaticilari_yukle():
    try:
        with HATIRLATICI_DOSYASI.open("r", encoding="utf-8") as reminders_file:
            reminders = json.load(reminders_file)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Hatırlatıcılar okunamadı.")
        raise RuntimeError("Hatırlatıcılar okunamadı; discord.log dosyasını inceleyin.") from exc

    if not isinstance(reminders, list):
        logger.error("Hatırlatıcı dosyasının biçimi geçersiz.")
        raise ValueError("Hatırlatıcı dosyasının biçimi geçersiz.")
    for reminder in reminders:
        if (
            not isinstance(reminder, dict)
            or not isinstance(reminder.get("id"), str)
            or not isinstance(reminder.get("message"), str)
            or not isinstance(reminder.get("due_at"), (int, float))
        ):
            logger.error("Hatırlatıcı dosyasında geçersiz bir kayıt var.")
            raise ValueError("Hatırlatıcı dosyasında geçersiz bir kayıt var.")
    return reminders


def hatirlaticilari_kaydet(reminders):
    temp_path = HATIRLATICI_DOSYASI.with_suffix(".json.tmp")
    try:
        temp_path.write_text(json.dumps(reminders, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, HATIRLATICI_DOSYASI)
    except OSError:
        temp_path.unlink(missing_ok=True)
        logger.exception("Hatırlatıcılar kaydedilemedi.")
        raise


class UygulamaKapatSelect(discord.ui.Select):
    def __init__(self, applications):
        options = []
        for app in applications[:25]:
            label_name = app[:100]
            options.append(discord.SelectOption(label=label_name, value=app))
        if not options:
            options.append(discord.SelectOption(label="Kapatılacak uygulama yok", value="yok"))
        super().__init__(placeholder="Kapatmak istediğiniz uygulamayı seçin...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "yok":
            await interaction.response.send_message("Kapatılacak geçerli bir uygulama seçilmedi.", ephemeral=True)
            return
        
        secilen = self.values[0]
        try:
            mesaj = await asyncio.to_thread(pc.uygulama_kapat, secilen)
            await interaction.response.send_message(embed=discord.Embed(title="İşlem Başarılı", description=mesaj, color=discord.Color.green()), ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(embed=hata_gomulusu_olustur("Uygulama Kapatılamadı", str(exc)), ephemeral=True)


class UygulamaSecimGorunumu(discord.ui.View):
    def __init__(self, applications):
        super().__init__(timeout=60)
        self.add_item(UygulamaKapatSelect(applications))


class UygulamaOneGetirSelect(discord.ui.Select):
    def __init__(self, applications):
        self.applications = applications[:25]
        options = [
            discord.SelectOption(label=app[:100], value=str(index))
            for index, app in enumerate(self.applications)
        ]
        if not options:
            options.append(discord.SelectOption(label="Öne getirilecek uygulama yok", value="yok"))
        super().__init__(
            placeholder="Öne getirmek istediğiniz uygulamayı seçin...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "yok":
            await interaction.response.send_message(
                "Öne getirilecek görünür bir uygulama bulunamadı.", ephemeral=True
            )
            return
        application = self.applications[int(self.values[0])]
        try:
            message, brought_to_front = await asyncio.to_thread(
                pc.uygulamayi_one_getir, application
            )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Seçilen uygulama öne getirilemedi.")
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Uygulama öne getirilemedi", str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title=(
                    "Uygulama öne getirildi"
                    if brought_to_front
                    else "Görev çubuğunda uyarı"
                ),
                description=message,
                color=(
                    discord.Color.green()
                    if brought_to_front
                    else discord.Color.orange()
                ),
            ),
            ephemeral=True,
        )


class UygulamaOneGetirGorunumu(discord.ui.View):
    def __init__(self, applications):
        super().__init__(timeout=60)
        self.add_item(UygulamaOneGetirSelect(applications))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if kullanima_yetkili_mi(interaction):
            return True
        await interaction.response.send_message(
            embed=hata_gomulusu_olustur(
                "Yetkisiz erişim", "Bu bilgisayar kontrol panelini kullanma iznin yok."
            ),
            ephemeral=True,
        )
        return False


class GucZamanlamaModal(discord.ui.Modal):
    def __init__(self, action):
        self.action = action
        title = "Yeniden başlatma zamanını ayarla" if action == "restart" else "Kapatma zamanını ayarla"
        super().__init__(title=title, timeout=180)
        self.delay_minutes = discord.ui.TextInput(
            label="Kaç dakika sonra? (1 - 10080)",
            placeholder="Örnek: 30",
            default="10",
            min_length=1,
            max_length=5,
        )
        self.add_item(self.delay_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        if not kullanima_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur(
                    "Yetkisiz erişim",
                    "Bu bilgisayar kontrol panelini kullanma iznin yok.",
                ),
                ephemeral=True,
            )
            return
        try:
            minutes = int(self.delay_minutes.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "Süreyi dakika olarak pozitif bir tam sayı gir.", ephemeral=True
            )
            return
        if not 1 <= minutes <= 10080:
            await interaction.response.send_message(
                "Süre 1 dakika ile 7 gün arasında olmalıdır.", ephemeral=True
            )
            return

        action_label = "yeniden başlatılacak" if self.action == "restart" else "kapatılacak"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Güç işlemini onayla",
                description=(
                    f"Bilgisayar **{minutes} dakika sonra {action_label}**. "
                    "İşlem başlamadan önce iptal edebilirsin."
                ),
                color=discord.Color.orange(),
            ),
            view=GucOnayGorunumu(self.action, minutes * 60),
            ephemeral=True,
        )


class HatirlaticiModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Hatırlatıcı kur", timeout=180)
        self.reminder_date = discord.ui.TextInput(
            label="Tarih (GG.AA.YYYY)",
            placeholder="Örnek: 25.12.2026",
            min_length=10,
            max_length=10,
        )
        self.reminder_time = discord.ui.TextInput(
            label="Saat (SS:DD)",
            placeholder="Örnek: 09:30",
            min_length=5,
            max_length=5,
        )
        self.reminder_message = discord.ui.TextInput(
            label="Hatırlatma notu",
            placeholder="Örnek: Fırını kapat",
            min_length=1,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.reminder_date)
        self.add_item(self.reminder_time)
        self.add_item(self.reminder_message)

    async def on_submit(self, interaction: discord.Interaction):
        if not kullanima_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur(
                    "Yetkisiz erişim",
                    "Bu bilgisayar kontrol panelini kullanma iznin yok.",
                ),
                ephemeral=True,
            )
            return
        try:
            due_at = hatirlatici_zamani_olustur(
                self.reminder_date.value, self.reminder_time.value
            )
        except ValueError as exc:
            await interaction.response.send_message(
                str(exc), ephemeral=True
            )
            return
        message = self.reminder_message.value.strip()
        if not message:
            await interaction.response.send_message(
                "Hatırlatma notu boş olamaz.", ephemeral=True
            )
            return

        if not isinstance(discord_istemcisi, DiscordKontrolIstemcisi):
            await interaction.response.send_message(
                "Hatırlatıcı hizmeti şu anda kullanılamıyor.", ephemeral=True
            )
            return
        try:
            reminder = discord_istemcisi.hatirlatici_ekle(message, due_at)
        except (OSError, ValueError) as exc:
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Hatırlatıcı kurulamadı", str(exc)),
                ephemeral=True,
            )
            return

        due_at = datetime.fromtimestamp(reminder["due_at"]).astimezone()
        embed = discord.Embed(
            title="⏰ Hatırlatıcı kuruldu",
            description="Alarmın hazır. Belirlenen zamanda bilgisayarda sesli uyarı açılacak.",
            color=discord.Color.blurple(),
            timestamp=due_at,
        )
        embed.add_field(name="📝 Hatırlatma", value=message, inline=False)
        embed.add_field(
            name="🔔 Bildirim",
            value="Bilgisayarda sesli pencere\nDiscord'a mesaj gönderilmez.",
            inline=True,
        )
        embed.set_footer(text="Bu hatırlatıcı yalnızca bu bilgisayarda çalışır")
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


class HatirlaticiSelect(discord.ui.Select):
    def __init__(self, reminders):
        self.reminders = reminders
        options = []
        for reminder in sorted(reminders, key=lambda item: item["due_at"])[:25]:
            due_at = datetime.fromtimestamp(reminder["due_at"]).astimezone()
            label = f"{due_at.strftime('%d.%m %H:%M')} · {reminder['message']}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=reminder["id"],
                    description=reminder["message"][:100],
                )
            )
        if not options:
            options.append(discord.SelectOption(label="Kurulu hatırlatıcı yok", value="yok"))
        super().__init__(
            placeholder="İptal etmek istediğiniz hatırlatıcıyı seçin...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "yok":
            await interaction.response.send_message(
                "İptal edilecek bir hatırlatıcı yok.", ephemeral=True
            )
            return
        if not isinstance(discord_istemcisi, DiscordKontrolIstemcisi):
            await interaction.response.send_message(
                "Hatırlatıcı hizmeti şu anda kullanılamıyor.", ephemeral=True
            )
            return
        try:
            removed = discord_istemcisi.hatirlatici_sil(self.values[0])
        except OSError as exc:
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Hatırlatıcı iptal edilemedi", str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Hatırlatıcı iptal edildi." if removed else "Hatırlatıcı artık bulunmuyor.",
            ephemeral=True,
        )


class HatirlaticiYonetimGorunumu(discord.ui.View):
    def __init__(self, reminders):
        super().__init__(timeout=120)
        self.add_item(HatirlaticiSelect(reminders))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if kullanima_yetkili_mi(interaction):
            return True
        await interaction.response.send_message(
            embed=hata_gomulusu_olustur(
                "Yetkisiz erişim", "Bu bilgisayar kontrol panelini kullanma iznin yok."
            ),
            ephemeral=True,
        )
        return False


class KontrolMenusuSelect(discord.ui.Select):
    def __init__(self):
        track_label = (
            "Uygulama takibini duraklat"
            if uygulama_kullanim_takibi_acik
            else "Uygulama takibini sürdür"
        )
        options = [
            discord.SelectOption(
                label="Sistem sağlığı ve öneriler", value="health", emoji="🩺"
            ),
            discord.SelectOption(label="Kaynak geçmişi", value="history", emoji="📈"),
            discord.SelectOption(label="Uygulama süreleri", value="usage", emoji="🎮"),
            discord.SelectOption(label="Günlük kullanım grafiği", value="usage_chart", emoji="📊"),
            discord.SelectOption(label="Başlangıç uygulamaları", value="startup_apps", emoji="🚀"),
            discord.SelectOption(label=track_label, value="toggle_usage", emoji="⏯️"),
            discord.SelectOption(label="Kullanım geçmişini sil", value="clear_usage", emoji="🧹"),
            discord.SelectOption(label="Ekran görüntüsü al", value="screenshot", emoji="🖼️"),
            discord.SelectOption(label="Uygulama kapat", value="kill_app", emoji="❌"),
            discord.SelectOption(label="Uygulamayı öne getir", value="focus_app", emoji="🪟"),
            discord.SelectOption(label="Hatırlatıcı kur", value="add_reminder", emoji="⏰"),
            discord.SelectOption(label="Hatırlatıcıları yönet", value="manage_reminders", emoji="📝"),
            discord.SelectOption(label="Yeniden başlat", value="restart", emoji="🔁"),
            discord.SelectOption(label="Bilgisayarı kapat", value="shutdown", emoji="🔴"),
            discord.SelectOption(label="Planlanan güç işlemini iptal et", value="cancel_power", emoji="🛑"),
        ]
        super().__init__(
            placeholder="Diğer işlemler...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="pc:menu",
        )

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, KontrolPaneliGorunumu):
            raise RuntimeError("Kontrol menüsü beklenen panele bağlı değil.")
        islem = self.values[0]
        handlers = {
            "health": panel.sistem_sagligi_raporu,
            "history": panel.kaynak_gecmisi,
            "usage": panel.uygulama_kullanim_sureleri,
            "usage_chart": panel.gunluk_kullanim_grafigi,
            "startup_apps": panel.baslangic_uygulamalari,
            "toggle_usage": panel.uygulama_takibini_degistir,
            "clear_usage": panel.kullanim_gecmisini_silme_iste,
            "screenshot": panel.ekran_goruntusu_gonder,
            "kill_app": panel.uygulama_kapat_menu,
            "focus_app": panel.uygulamayi_one_getir_menu,
            "add_reminder": panel.hatirlatici_kur,
            "manage_reminders": panel.hatirlaticilari_yonet,
            "restart": panel.yeniden_baslatma_iste,
            "shutdown": panel.bilgisayari_kapatma_iste,
            "cancel_power": panel.guc_islemini_iptal_et,
        }
        await handlers[islem](interaction, None)


class KontrolPaneliGorunumu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(KontrolMenusuSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if kullanima_yetkili_mi(interaction):
            return True
        await interaction.response.send_message(
            embed=hata_gomulusu_olustur("Yetkisiz erişim", "Bu bilgisayar kontrol panelini kullanma iznin yok."),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Durumu yenile", emoji="🔄", style=discord.ButtonStyle.primary, custom_id="pc:refresh", row=0)
    async def durumu_yenile(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except Exception as exc:
            await interaction.response.send_message(embed=hata_gomulusu_olustur("Durum alınamadı", str(exc)), ephemeral=True)
            return
        await interaction.response.edit_message(embed=embed, view=self)

    async def sistem_sagligi_raporu(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status = await asyncio.to_thread(pc.durum_topla, kaydet_gecmis=False)
        except RuntimeError as exc:
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("Sistem sağlığı okunamadı", str(exc)),
                ephemeral=True,
            )
            return

        health = sistem_sagligi_ozetini_olustur(status)
        description = (
            "\n".join(f"• {warning}" for warning in health["uyarilar"])
            if health["uyarilar"]
            else "Güncel CPU, bellek, disk ve erişilebilen sıcaklık değerlerinde yüksek kullanım yok."
        )
        color = (
            discord.Color.red()
            if health["durum"] == "Kritik"
            else discord.Color.orange()
            if health["durum"] == "Dikkat"
            else discord.Color.blurple()
        )
        embed = discord.Embed(
            title=f"{health['emoji']} Sistem sağlığı: {health['durum']}",
            description=description,
            color=color,
            timestamp=datetime.now().astimezone(),
        )
        if health["oneriler"]:
            embed.add_field(
                name="Öneriler",
                value="\n".join(f"• {recommendation}" for recommendation in health["oneriler"]),
                inline=False,
            )
        if health["eksik_veriler"]:
            embed.add_field(
                name="Eksik ölçümler",
                value="\n".join(f"• {item}" for item in health["eksik_veriler"]),
                inline=False,
            )
        embed.set_footer(
            text="Yalnızca anlık ölçümlere dayanır; hiçbir işlem otomatik yapılmaz."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def ekran_goruntusu_gonder(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            image = await asyncio.to_thread(pc.ekran_goruntusu_al)
        except Exception as exc:
            await interaction.followup.send(embed=hata_gomulusu_olustur("Ekran görüntüsü alınamadı", str(exc)), ephemeral=True)
            return
        embed = discord.Embed(
            title="🖼️ Anlık ekran görüntüsü",
            description="Masaüstü anlık görüntüsü başarıyla alındı.",
            color=discord.Color.blurple(),
            timestamp=datetime.now().astimezone(),
        )
        embed.set_image(url="attachment://pc-ekran.jpg")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(image, filename="pc-ekran.jpg"),
            ephemeral=True,
        )

    async def uygulama_kapat_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            apps, _ = pc.acik_uygulamalari_topla()
        except (OSError, RuntimeError) as exc:
            logger.exception("Kapatılabilir uygulamalar listelenemedi.")
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Uygulamalar listelenemedi", str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(title="Uygulama Kapatma", description="Aşağıdaki menüden sonlandırmak istediğiniz uygulamayı seçin.", color=discord.Color.orange()),
            view=UygulamaSecimGorunumu(apps),
            ephemeral=True
        )

    async def uygulamayi_one_getir_menu(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        try:
            apps, _ = pc.acik_uygulamalari_topla()
        except (OSError, RuntimeError) as exc:
            logger.exception("Öne getirilebilir uygulamalar listelenemedi.")
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Uygulamalar listelenemedi", str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Uygulamayı öne getir",
                description="Ön plana almak istediğiniz görünür uygulamayı seçin.",
                color=discord.Color.blurple(),
            ),
            view=UygulamaOneGetirGorunumu(apps),
            ephemeral=True,
        )

    async def hatirlatici_kur(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(HatirlaticiModal())

    async def hatirlaticilari_yonet(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(discord_istemcisi, DiscordKontrolIstemcisi):
            await interaction.response.send_message(
                "Hatırlatıcı hizmeti şu anda kullanılamıyor.", ephemeral=True
            )
            return
        reminders = discord_istemcisi.reminders
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"Hatırlatıcılar ({len(reminders)})",
                description=(
                    "İptal etmek istediğiniz hatırlatıcıyı seçin."
                    if reminders
                    else "Henüz hatırlatıcı kurulmadı."
                ),
                color=discord.Color.blurple(),
            ),
            view=HatirlaticiYonetimGorunumu(reminders),
            ephemeral=True,
        )

    async def yeniden_baslatma_iste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GucZamanlamaModal("restart"))

    async def bilgisayari_kapatma_iste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GucZamanlamaModal("shutdown"))

    async def kaynak_gecmisi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(title="Kaynak kullanım geçmişi", description="İstediğiniz zaman aralığını seçin.", color=discord.Color.blurple()),
            view=GecmisAraligiGorunumu(),
            ephemeral=True,
        )

    async def guc_islemini_iptal_et(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await asyncio.to_thread(pc.guc_islemi_yurut, "cancel")
        except Exception as exc:
            await interaction.followup.send(embed=hata_gomulusu_olustur("İptal edilemedi", str(exc)), ephemeral=True)
            return
        try:
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except Exception:
            logger.exception("Güç işlemi iptal edildi ancak durum Embed'i yenilenemedi.")
            await interaction.followup.send(
                embed=discord.Embed(
                    title="İşlem iptal edildi",
                    description="Panel 60 saniye içinde otomatik yenilenecek.",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )
            return
        await interaction.edit_original_response(embed=embed, view=self)

    async def uygulama_kullanim_sureleri(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            usages = await asyncio.to_thread(pc.uygulama_kullanim_ozetini_getir, 7)
        except RuntimeError as exc:
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("Kullanım geçmişi alınamadı", str(exc)),
                ephemeral=True,
            )
            return

        total_seconds = sum(item["saniye"] for item in usages)
        if usages:
            lines = []
            for rank, item in enumerate(usages[:10], start=1):
                name = item["ad"].replace("`", "ˋ").replace("\n", " ")[:48]
                duration = (
                    f"{item['saniye']} sn"
                    if item["saniye"] < 60
                    else pc.sureyi_bicimlendir(item["saniye"])
                )
                lines.append(f"**{rank}.** `{name}` — {duration}")
            description = "\n".join(lines)
            if len(usages) > 10:
                description += f"\n… ve {len(usages) - 10} uygulama daha"
        else:
            description = "Henüz gösterilecek kullanım kaydı yok."

        status_text = (
            "Takip açık."
            if uygulama_kullanim_takibi_acik
            else "Yeni kayıt için kurulumda aktif pencere takibini açmalısın."
        )
        embed = discord.Embed(
            title="🎮 Son 7 gün • Uygulama süreleri",
            description=f"{status_text}\n\n{description}",
            color=discord.Color.blurple(),
            timestamp=datetime.now().astimezone(),
        )
        embed.add_field(
            name="Toplam ölçülen aktif süre",
            value=(
                f"{total_seconds} sn"
                if total_seconds < 60
                else pc.sureyi_bicimlendir(total_seconds)
            ),
            inline=False,
        )
        embed.set_footer(
            text="Yalnızca uygulama adları saklanır; pencere başlığı ve içerikleri izlenmez."
        )
        await interaction.followup.send(
            embed=embed,
            view=UygulamaKullanimGecmisiGorunumu(),
            ephemeral=True,
        )

    async def gunluk_kullanim_grafigi(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            grafik = await asyncio.to_thread(pc.uygulama_kullanim_grafigi_olustur, 7)
        except RuntimeError as exc:
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("Kullanım grafiği oluşturulamadı", str(exc)),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="📊 Son 7 gün • Günlük uygulama kullanımı",
            description="Her günün ölçülen aktif pencere süreleri.",
            color=discord.Color.blurple(),
        )
        embed.set_image(url="attachment://uygulama-kullanimi.png")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(grafik, filename="uygulama-kullanimi.png"),
            ephemeral=True,
        )

    async def baslangic_uygulamalari(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            applications = await asyncio.to_thread(pc.baslangic_uygulamalarini_topla)
        except (OSError, RuntimeError, ImportError) as exc:
            logger.exception("Windows başlangıç uygulamaları listelenemedi.")
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("Başlangıç uygulamaları okunamadı", str(exc)),
                ephemeral=True,
            )
            return
        lines = [f"• `{name.replace('`', 'ˋ')[:72]}`" for name in applications[:15]]
        if len(applications) > 15:
            lines.append(f"… ve {len(applications) - 15} uygulama daha")
        embed = discord.Embed(
            title=f"🚀 Windows başlangıç uygulamaları ({len(applications)})",
            description="\n".join(lines) if lines else "Başlangıç uygulaması bulunamadı.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Salt okunur liste; uygulama veya başlangıç ayarı değiştirilmez.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def uygulama_takibini_degistir(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        global uygulama_kullanim_takibi_acik
        yeni_durum = not uygulama_kullanim_takibi_acik
        try:
            await asyncio.to_thread(pc.uygulama_kullanim_takibini_ayarla, yeni_durum)
            uygulama_kullanim_takibi_acik = yeni_durum
        except (RuntimeError, OSError, ValueError) as exc:
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Takip ayarı değiştirilemedi", str(exc)),
                ephemeral=True,
            )
            return
        try:
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except Exception:
            logger.exception("Uygulama takibi değişti ancak durum Embed'i yenilenemedi.")
            await interaction.response.edit_message(view=KontrolPaneliGorunumu())
            await interaction.followup.send(
                content=(
                    "Uygulama kullanım takibi "
                    f"{'açıldı' if yeni_durum else 'duraklatıldı'}; "
                    "durum paneli sonraki otomatik yenilemede güncellenecek."
                ),
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(embed=embed, view=KontrolPaneliGorunumu())

    async def kullanim_gecmisini_silme_iste(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Uygulama kullanım geçmişini sil?",
                description=(
                    "Bu işlem bu bilgisayardaki son 7 günlük uygulama sürelerini siler. "
                    "Takip açıksa yeni kayıtlar daha sonra yeniden oluşabilir."
                ),
                color=discord.Color.orange(),
            ),
            view=UygulamaKullanimSilmeOnayi(),
            ephemeral=True,
        )


class GecmisAraligiGorunumu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    async def grafiki_gonder(self, interaction, saat):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            grafik = await asyncio.to_thread(pc.gecmis_grafigi_olustur, saat)
        except Exception as exc:
            await interaction.followup.send(embed=hata_gomulusu_olustur("Grafik oluşturulamadı", str(exc)), ephemeral=True)
            return
        embed = discord.Embed(title=f"📈 Son {saat} saat • Kaynak kullanımı", color=discord.Color.blurple())
        embed.set_image(url="attachment://kaynak-gecmisi.png")
        await interaction.followup.send(embed=embed, file=discord.File(grafik, filename="kaynak-gecmisi.png"), ephemeral=True)

    @discord.ui.button(label="1 saat", style=discord.ButtonStyle.primary, custom_id="pc:history:1h")
    async def bir_saat(self, interaction, button):
        await self.grafiki_gonder(interaction, 1)

    @discord.ui.button(label="24 saat", style=discord.ButtonStyle.primary, custom_id="pc:history:24h")
    async def yirmi_dort_saat(self, interaction, button):
        await self.grafiki_gonder(interaction, 24)

    @discord.ui.button(label="7 gün", style=discord.ButtonStyle.primary, custom_id="pc:history:7d")
    async def yedi_gun(self, interaction, button):
        await self.grafiki_gonder(interaction, 168)


class UygulamaKullanimSilmeOnayi(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Geçmişi sil", style=discord.ButtonStyle.danger)
    async def gecmisi_sil(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        try:
            await asyncio.to_thread(pc.uygulama_kullanim_gecmisini_sil)
        except RuntimeError as exc:
            await interaction.edit_original_response(
                embed=hata_gomulusu_olustur("Geçmiş silinemedi", str(exc)),
                view=None,
            )
            return
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="Uygulama kullanım geçmişi silindi",
                description="Yerel veritabanındaki uygulama kullanım kayıtları silindi.",
                color=discord.Color.green(),
            ),
            view=None,
        )

    @discord.ui.button(label="Vazgeç", style=discord.ButtonStyle.secondary)
    async def silmeyi_iptal_et(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Silme işlemi iptal edildi",
                color=discord.Color.dark_grey(),
            ),
            view=None,
        )


class UygulamaKullanimGecmisiGorunumu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Yerel geçmişi sil", style=discord.ButtonStyle.danger)
    async def gecmisi_silme_iste(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Uygulama kullanım geçmişini sil?",
                description=(
                    "Bu işlem bu bilgisayardaki son 7 günlük uygulama sürelerini siler. "
                    "Takip açıksa yeni kayıtlar daha sonra yeniden oluşabilir."
                ),
                color=discord.Color.orange(),
            ),
            view=UygulamaKullanimSilmeOnayi(),
            ephemeral=True,
        )


class GucOnayGorunumu(discord.ui.View):
    def __init__(self, action: str, delay_seconds: int):
        super().__init__(timeout=60)
        self.action = action
        self.delay_seconds = delay_seconds

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if kullanima_yetkili_mi(interaction):
            return True
        await interaction.response.send_message(
            embed=hata_gomulusu_olustur(
                "Yetkisiz erişim", "Bu bilgisayar kontrol panelini kullanma iznin yok."
            ),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Onayla", style=discord.ButtonStyle.danger, custom_id="pc:confirm-power")
    async def onayla(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(
                pc.guc_islemi_yurut, self.action, self.delay_seconds
            )
        except Exception as exc:
            await interaction.edit_original_response(embed=hata_gomulusu_olustur("İşlem başlatılamadı", str(exc)), view=None)
            return
        await interaction.edit_original_response(embed=discord.Embed(title="✅ İşlem onaylandı", description=result, color=discord.Color.orange()), view=None)

    @discord.ui.button(label="Vazgeç", style=discord.ButtonStyle.secondary, custom_id="pc:cancel-confirmation")
    async def vazgec(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=discord.Embed(title="İşlem yapılmadı", color=discord.Color.dark_grey()), view=None)


class DiscordKontrolIstemcisi(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.panel_message: discord.Message | None = None
        self.panel_task: asyncio.Task | None = None
        self.reminder_task: asyncio.Task | None = None
        self.reminder_popup_tasks: set[asyncio.Task] = set()
        self.reminders = hatirlaticilari_yukle()

    async def setup_hook(self) -> None:
        self.add_view(KontrolPaneliGorunumu())
        guild = discord.Object(id=sunucu_kimligi)
        self.tree.clear_commands(guild=None)
        self.tree.clear_commands(guild=guild)
        await self.tree.sync()
        await self.tree.sync(guild=guild)
        logger.info("Genel ve sunucu slash komutları temizlendi; botta slash komutu yok.")

    async def on_ready(self) -> None:
        logger.info("Discord kontrol botu hazır: %s", self.user)
        if self.reminder_task is None or self.reminder_task.done():
            self.reminder_task = asyncio.create_task(
                self.hatirlaticilari_calistir(), name="pc-reminder-scheduler"
            )
        try:
            await self.kontrol_panelini_hazirla()
            hazirlik_durumunu_yaz()
        except Exception:
            hazirlik_durumunu_temizle()
            logger.exception("Discord kontrol paneli başlatılamadı.")
            return
        if self.panel_task is None or self.panel_task.done():
            self.panel_task = asyncio.create_task(self.kontrol_panelini_yenile(), name="pc-control-embed-refresh")

    def hatirlatici_ekle(self, message: str, due_at: datetime):
        if len(self.reminders) >= 25:
            raise ValueError("En fazla 25 etkin hatırlatıcı kurabilirsin.")
        if due_at.tzinfo is None or due_at.utcoffset() is None:
            raise ValueError("Hatırlatıcı zamanı saat dilimi içermelidir.")
        due_timestamp = due_at.timestamp()
        if due_timestamp <= time.time():
            raise ValueError("Hatırlatıcı zamanı gelecekte olmalıdır.")
        reminder = {
            "id": uuid.uuid4().hex,
            "due_at": due_timestamp,
            "message": message,
        }
        self.reminders.append(reminder)
        try:
            hatirlaticilari_kaydet(self.reminders)
        except OSError:
            self.reminders.remove(reminder)
            raise
        return reminder

    def hatirlatici_sil(self, reminder_id: str) -> bool:
        reminder = next(
            (item for item in self.reminders if item["id"] == reminder_id), None
        )
        if reminder is None:
            return False
        self.reminders.remove(reminder)
        try:
            hatirlaticilari_kaydet(self.reminders)
        except OSError:
            self.reminders.append(reminder)
            raise
        return True

    async def hatirlatici_masaustu_uyarisini_goster(self, reminder) -> None:
        try:
            await asyncio.to_thread(
                masaustu_bildirimi_goster, reminder["message"]
            )
        except OSError:
            logger.exception("Hatırlatıcı Windows masaüstünde gösterilemedi.")

    def masaustu_uyarisi_gorevini_tamamla(self, task: asyncio.Task) -> None:
        self.reminder_popup_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            logger.error(
                "Hatırlatıcı masaüstü uyarısı beklenmeyen bir hatayla sonlandı.",
                exc_info=(type(exception), exception, exception.__traceback__),
            )

    async def hatirlaticilari_calistir(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            if not self.reminders:
                await asyncio.sleep(30)
                continue
            reminder = min(self.reminders, key=lambda item: item["due_at"])
            remaining = reminder["due_at"] - time.time()
            if remaining > 0:
                await asyncio.sleep(min(remaining, 30))
                continue
            popup_task = asyncio.create_task(
                self.hatirlatici_masaustu_uyarisini_goster(reminder),
                name=f"pc-reminder-popup-{reminder['id']}",
            )
            self.reminder_popup_tasks.add(popup_task)
            popup_task.add_done_callback(
                self.masaustu_uyarisi_gorevini_tamamla
            )
            self.reminders.remove(reminder)
            try:
                hatirlaticilari_kaydet(self.reminders)
            except OSError:
                logger.exception(
                    "Tetiklenen hatırlatıcı diskten kaldırılamadı."
                )

    async def on_disconnect(self) -> None:
        hazirlik_durumunu_temizle()

    async def kontrol_panelini_hazirla(self) -> None:
        channel = self.get_channel(kontrol_kanali_kimligi) or await self.fetch_channel(kontrol_kanali_kimligi)
        message_id = None
        try:
            with PANEL_DOSYASI.open("r", encoding="utf-8") as panel_file:
                message_id = json.load(panel_file).get("message_id")
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            logger.warning("Kayıtlı kontrol paneli mesajı okunamadı: %s", exc)

        if message_id:
            try:
                self.panel_message = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                pass

        embed = await asyncio.to_thread(durum_gomulusu_olustur)
        if self.panel_message is None:
            self.panel_message = await channel.send(embed=embed, view=KontrolPaneliGorunumu())
            temp_path = PANEL_DOSYASI.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps({"message_id": self.panel_message.id}), encoding="utf-8")
            os.replace(temp_path, PANEL_DOSYASI)
        else:
            await self.panel_message.edit(embed=embed, view=KontrolPaneliGorunumu())

    async def kontrol_panelini_guncelle(self, embed=None) -> None:
        if self.panel_message is None:
            await self.kontrol_panelini_hazirla()
        if embed is None:
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        await self.panel_message.edit(embed=embed, view=KontrolPaneliGorunumu())

    async def kontrol_panelini_yenile(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.kontrol_panelini_guncelle()
            except Exception:
                logger.exception("Discord kontrol paneli yenilenemedi.")
            await asyncio.sleep(60)


def hazirlik_durumunu_yaz() -> None:
    temp_path = HAZIRLIK_DOSYASI.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    os.replace(temp_path, HAZIRLIK_DOSYASI)


def hazirlik_durumunu_temizle() -> None:
    try:
        HAZIRLIK_DOSYASI.unlink(missing_ok=True)
    except Exception:
        pass


async def botu_baslat() -> None:
    global bot_olay_dongusu, discord_istemcisi
    bot_olay_dongusu = asyncio.get_running_loop()
    discord_istemcisi = DiscordKontrolIstemcisi()
    await discord_istemcisi.start(bot_anahtari)


def botu_calistir() -> None:
    global baslangic_hatasi
    try:
        asyncio.run(botu_baslat())
    except Exception as exc:
        baslangic_hatasi = str(exc)
        hazirlik_durumunu_temizle()


def botu_durdur() -> None:
    if discord_istemcisi and bot_olay_dongusu and not discord_istemcisi.is_closed():
        asyncio.run_coroutine_threadsafe(discord_istemcisi.close(), bot_olay_dongusu)