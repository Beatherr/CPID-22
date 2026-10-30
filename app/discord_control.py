import asyncio
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

import discord
from discord import app_commands

import client as pc


UYGULAMA_ADI = "PCActivityMonitor"
DURUM_DIZINI = Path(os.environ["APPDATA"]) / UYGULAMA_ADI
AYAR_DOSYASI = DURUM_DIZINI / "config.json"
PANEL_DOSYASI = DURUM_DIZINI / "discord_panel.json"
HAZIRLIK_DOSYASI = DURUM_DIZINI / "discord_ready.json"
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
bot_olay_dongusu = None
discord_istemcisi = None
baslangic_hatasi = None


def kullanima_yetkili_mi(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.id == yetkili_kullanici_kimligi
        and interaction.guild_id == sunucu_kimligi
        and interaction.channel_id == kontrol_kanali_kimligi
    )


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
            "Bilgisayar durumu ve güvenli kontroller aşağıda. "
            "Yeni özellikler ile uygulama kapatma ve detaylı ekran görüntüleri yönetilebilir."
        ),
        color=discord.Color.green(),
        timestamp=now,
    )
    embed.add_field(
        name="💻 Bilgisayar",
        value=(
            f"**Ad:** `{status['bilgisayar_adi']}`\n"
            f"**Windows hesabı:** `{status['kullanici_adi']}`\n"
            f"**Durum:** 🟢 Çevrimiçi"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚙️ İşlemci",
        value=(
            f"**Kullanım:** {status['cpu']}%\n"
            f"**Model:** {status['cpu_modeli']}\n"
            f"**Çekirdek / izlek:** {status['cpu_cekirdek']} / {status['cpu_izlek']}\n"
            f"**Anlık frekans:** {status['cpu_frekans_mhz'] or 'Yok'} MHz"
        ),
        inline=True,
    )
    embed.add_field(
        name="🧠 Bellek",
        value=(
            f"**Kullanım:** {status['bellek_yuzde']}% "
            f"({status['bellek_kullanilan_gb']} / {status['bellek_toplam_gb']} GB)\n"
            f"**Kullanılabilir:** {status['bellek_kullanilabilir_gb']} GB"
        ),
        inline=True,
    )
    embed.add_field(
        name="💽 Sistem diski",
        value=(
            f"**Kullanım:** {status['disk_kullanilan_yuzde']}%\n"
            f"**Boş alan:** {status['disk_bos_gb']} / {status['disk_toplam_gb']} GB"
        ),
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
    embed.add_field(name="🌐 Ağ trafiği", value=ag_metni, inline=True)

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
    embed.add_field(
        name="📊 En çok kaynak kullanan süreçler",
        value=surec_metni,
        inline=False,
    )
    applications = status["acik_uygulamalar"]
    application_lines = applications[:10]
    embed.add_field(
        name=f"🪟 Açık uygulamalar ({len(applications)})",
        value="\n".join([f"• `{name[:48]}`" for name in application_lines])
        if application_lines
        else "Görünür uygulama penceresi bulunamadı.",
        inline=False,
    )
    embed.add_field(name="🔌 Güç işlemi", value=power_state, inline=False)
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


class KontrolPaneliGorunumu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

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

    @discord.ui.button(label="Ekran görüntüsü", emoji="🖼️", style=discord.ButtonStyle.secondary, custom_id="pc:screenshot", row=0)
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

    @discord.ui.button(label="Uygulama Kapat", emoji="❌", style=discord.ButtonStyle.danger, custom_id="pc:kill_app", row=1)
    async def uygulama_kapat_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            apps, _ = pc.acik_uygulamalari_topla()
        except Exception:
            apps = []
        await interaction.response.send_message(
            embed=discord.Embed(title="Uygulama Kapatma", description="Aşağıdaki menüden sonlandırmak istediğiniz uygulamayı seçin.", color=discord.Color.orange()),
            view=UygulamaSecimGorunumu(apps),
            ephemeral=True
        )

    @discord.ui.button(label="Yeniden başlat", emoji="🔁", style=discord.ButtonStyle.primary, custom_id="pc:restart", row=2)
    async def yeniden_baslatma_iste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(title="Yeniden başlatma onayı", description="Bilgisayar 60 saniye sonra yeniden başlatılacak.", color=discord.Color.orange()),
            view=GucOnayGorunumu("restart"),
            ephemeral=True,
        )

    @discord.ui.button(label="Bilgisayarı kapat", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="pc:shutdown", row=2)
    async def bilgisayari_kapatma_iste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(title="Kapatma onayı", description="Bilgisayar 60 saniye sonra kapatılacak.", color=discord.Color.red()),
            view=GucOnayGorunumu("shutdown"),
            ephemeral=True,
        )

    @discord.ui.button(label="Kaynak geçmişi", emoji="📈", style=discord.ButtonStyle.secondary, custom_id="pc:history", row=1)
    async def kaynak_gecmisi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(title="Kaynak kullanım geçmişi", description="İstediğiniz zaman aralığını seçin.", color=discord.Color.blurple()),
            view=GecmisAraligiGorunumu(),
            ephemeral=True,
        )

    @discord.ui.button(label="İşlemi iptal et", emoji="🛑", style=discord.ButtonStyle.secondary, custom_id="pc:cancel", row=2)
    async def guc_islemini_iptal_et(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            message = await asyncio.to_thread(pc.guc_islemi_yurut, "cancel")
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except Exception as exc:
            await interaction.followup.send(embed=hata_gomulusu_olustur("İptal edilemedi", str(exc)), ephemeral=True)
            return
        await interaction.edit_original_response(embed=embed, view=self)


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


class GucOnayGorunumu(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.action = action

    @discord.ui.button(label="Onayla", style=discord.ButtonStyle.danger, custom_id="pc:confirm-power")
    async def onayla(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(pc.guc_islemi_yurut, self.action)
            status_embed = await asyncio.to_thread(durum_gomulusu_olustur)
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

    async def setup_hook(self) -> None:
        self.add_view(KontrolPaneliGorunumu())
        self.tree.clear_commands(guild=discord.Object(id=sunucu_kimligi))
        await self.tree.sync(guild=discord.Object(id=sunucu_kimligi))

    async def on_ready(self) -> None:
        logger.info("Discord kontrol botu hazır: %s", self.user)
        try:
            await self.kontrol_panelini_hazirla()
            hazirlik_durumunu_yaz()
        except Exception:
            hazirlik_durumunu_temizle()
            logger.exception("Discord kontrol paneli başlatılamadı.")
            return
        if self.panel_task is None or self.panel_task.done():
            self.panel_task = asyncio.create_task(self.kontrol_panelini_yenile(), name="pc-control-embed-refresh")

    async def on_disconnect(self) -> None:
        hazirlik_durumunu_temizle()

    async def kontrol_panelini_hazirla(self) -> None:
        channel = self.get_channel(kontrol_kanali_kimligi) or await self.fetch_channel(kontrol_kanali_kimligi)
        message_id = None
        try:
            with PANEL_DOSYASI.open("r", encoding="utf-8") as panel_file:
                message_id = json.load(panel_file).get("message_id")
        except Exception:
            pass

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
                pass
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