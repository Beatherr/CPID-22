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
            "İşlemler yalnızca bu özel kanalda yetkili hesabınla kullanılabilir."
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
        if status["okunamayan_surec_sayisi"]:
            surec_metni += (
                f"\n{status['okunamayan_surec_sayisi']} süreç için erişim izni yok."
            )
    else:
        surec_metni = "Kaynak kullanan süreç bulunamadı."
    embed.add_field(
        name="📊 En çok kaynak kullanan süreçler",
        value=surec_metni,
        inline=False,
    )
    applications = status["acik_uygulamalar"]
    application_lines = applications[:12]
    if len(applications) > len(application_lines):
        application_lines.append(f"+{len(applications) - len(application_lines)} uygulama daha")
    if status["okunamayan_uygulama_sayisi"]:
        application_lines.append(
            f"{status['okunamayan_uygulama_sayisi']} uygulamanın adı okunamadı"
        )
    if status["uygulama_hatasi"]:
        application_lines = [status["uygulama_hatasi"]]
    embed.add_field(
        name=f"🪟 Açık uygulamalar ({len(applications)})",
        value="\n".join(
            application_lines
            if status["uygulama_hatasi"]
            else [f"• `{name[:48]}`" for name in application_lines]
        )
        if application_lines
        else "Görünür uygulama penceresi bulunamadı.",
        inline=False,
    )
    embed.add_field(name="🔌 Güç işlemi", value=power_state, inline=False)
    if status["gecmis_hatasi"]:
        embed.add_field(
            name="📈 Geçmiş kaydı",
            value=status["gecmis_hatasi"],
            inline=False,
        )
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


class KontrolPaneliGorunumu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if kullanima_yetkili_mi(interaction):
            return True
        logger.warning(
            "%s kullanıcısının %s sunucusu ve %s kanalındaki panel isteği reddedildi.",
            interaction.user.id,
            interaction.guild_id,
            interaction.channel_id,
        )
        await interaction.response.send_message(
            embed=hata_gomulusu_olustur(
                "Yetkisiz erişim",
                "Bu bilgisayar kontrol panelini kullanma iznin yok.",
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return False

    @discord.ui.button(
        label="Durumu yenile",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
        custom_id="pc:refresh",
        row=0,
    )
    async def durumu_yenile(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        try:
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            logger.exception("Discord kontrol paneli yenilenemedi.")
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Durum alınamadı", str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Ekran görüntüsü",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary,
        custom_id="pc:screenshot",
        row=0,
    )
    async def ekran_goruntusu_gonder(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            image = await asyncio.to_thread(pc.ekran_goruntusu_al)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Discord kontrol paneli için ekran görüntüsü alınamadı.")
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("Ekran görüntüsü alınamadı", str(exc)),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🖼️ Anlık ekran görüntüsü",
            description="Görüntü yalnızca bu etkileşim yanıtında sana gösterilir.",
            color=discord.Color.blurple(),
            timestamp=datetime.now().astimezone(),
        )
        embed.set_image(url="attachment://pc-ekran.jpg")
        embed.set_footer(text="Bu görüntü, düğmeye bastığın anda alındı.")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(image, filename="pc-ekran.jpg"),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Yeniden başlat",
        emoji="🔁",
        style=discord.ButtonStyle.primary,
        custom_id="pc:restart",
        row=0,
    )
    async def yeniden_baslatma_iste(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔁 Yeniden başlatma onayı",
                description=(
                    "Bilgisayar **60 saniye sonra** yeniden başlatılacak. "
                    "Açık işlerini kaydet. Onaydan sonra işlemi **İşlemi iptal et** "
                    "düğmesiyle geri alabilirsin."
                ),
                color=discord.Color.orange(),
            ),
            view=GucOnayGorunumu("restart"),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Bilgisayarı kapat",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="pc:shutdown",
        row=0,
    )
    async def bilgisayari_kapatma_iste(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔴 Kapatma onayı",
                description=(
                    "Bilgisayar **60 saniye sonra** kapatılacak. Açık işlerini kaydet. "
                    "Onaydan sonra işlemi **İşlemi iptal et** düğmesiyle geri alabilirsin."
                ),
                color=discord.Color.red(),
            ),
            view=GucOnayGorunumu("shutdown"),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Kaynak geçmişi",
        emoji="📈",
        style=discord.ButtonStyle.secondary,
        custom_id="pc:history",
        row=1,
    )
    async def kaynak_gecmisi(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📈 Kaynak kullanım geçmişi",
                description=(
                    "CPU, bellek ve disk ölçümleri bu bilgisayarda yerel olarak "
                    "7 güne kadar tutulur. Bir aralık seçtiğinde grafik Discord'a "
                    "yalnızca sana özel yanıt olarak gönderilir."
                ),
                color=discord.Color.blurple(),
            ),
            view=GecmisAraligiGorunumu(),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="İşlemi iptal et",
        emoji="🛑",
        style=discord.ButtonStyle.secondary,
        custom_id="pc:cancel",
        row=1,
    )
    async def guc_islemini_iptal_et(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.defer()
        try:
            message = await asyncio.to_thread(pc.guc_islemi_yurut, "cancel")
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("İşlem iptal edilemedi", str(exc)),
                ephemeral=True,
            )
            return
        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Güç işlemi iptal edildi",
                description=message,
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Yardım ve gizlilik",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="pc:help",
        row=1,
    )
    async def yardim_ve_gizliligi_goster(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        embed = discord.Embed(
            title="ℹ️ Kontrol paneli • yardım ve gizlilik",
            description=(
                "Bu panel bu bilgisayarın kişisel kontrolü içindir. "
                "Butonlar dışından komut veya dosya çalıştırma özelliği yoktur."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Kontroller",
            value=(
                "🔄 **Durumu yenile:** CPU, bellek, disk ve sistem bilgilerini yeniler.\n"
                "🪟 **Açık uygulamalar:** Görünür pencere sahibi uygulamaların adlarını gösterir; pencere başlıklarını paylaşmaz.\n"
                "📊 **Kaynak süreçleri:** En çok bellek kullanan beş sürecin adı, RAM ve CPU kullanımını gösterir.\n"
                "🌐 **Ağ trafiği:** Windows açılışından beri gönderilen/alınan toplamı ve yaklaşık anlık hızı gösterir.\n"
                "📈 **Kaynak geçmişi:** CPU, bellek ve disk grafiğini 1 saat, 24 saat veya 7 gün için gönderir.\n"
                "🖼️ **Ekran görüntüsü:** Yalnızca istediğinde anlık görüntüyü sana özel yollar.\n"
                "🔁 **Yeniden başlat / 🔴 Kapat:** İkinci onay ister; 60 sn gecikmeli çalışır.\n"
                "🛑 **İşlemi iptal et:** Bekleyen güç işlemini durdurur."
            ),
            inline=False,
        )
        embed.add_field(
            name="Yetki ve veri",
            value=(
                "İşlemler sadece kurulumda seçilen kullanıcı, sunucu ve kanalda kabul edilir. "
                "Açık uygulama ve en çok kaynak kullanan süreç adları, sistem durumu ve ağ "
                "sayacı özeti kontrol kanalına gönderilir. Geçmiş bilgisayarda 7 gün tutulur; "
                "grafik yalnızca istediğinde sana özel gönderilir. Pencere başlıkları alınmaz. "
                "Bot token'ını paylaşma; bu kanalı özel tut."
            ),
            inline=False,
        )
        embed.add_field(
            name="Sorun giderme",
            value=(
                "Bilgisayar açık, Windows oturumu açık ve internet bağlantısı olmalı. "
                "Panel mesajını yanlışlıkla silersen uygulamayı yeniden başlat; panel "
                "mesajını oluşturur."
            ),
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class GecmisAraligiGorunumu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    async def grafiki_gonder(self, interaction, saat):
        if not kullanima_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Yetkisiz erişim", "Bu işlem için iznin yok."),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            grafik = await asyncio.to_thread(pc.gecmis_grafigi_olustur, saat)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Kaynak kullanım grafiği oluşturulamadı.")
            await interaction.followup.send(
                embed=hata_gomulusu_olustur("Grafik oluşturulamadı", str(exc)),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title=f"📈 Son {saat} saat • Kaynak kullanımı",
            description="Ölçümler yerel geçmiş veritabanından oluşturuldu.",
            color=discord.Color.blurple(),
            timestamp=datetime.now().astimezone(),
        )
        embed.set_image(url="attachment://kaynak-gecmisi.png")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(grafik, filename="kaynak-gecmisi.png"),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="1 saat",
        style=discord.ButtonStyle.primary,
        custom_id="pc:history:1h",
    )
    async def bir_saat(self, interaction, button):
        _ = button
        await self.grafiki_gonder(interaction, 1)

    @discord.ui.button(
        label="24 saat",
        style=discord.ButtonStyle.primary,
        custom_id="pc:history:24h",
    )
    async def yirmi_dort_saat(self, interaction, button):
        _ = button
        await self.grafiki_gonder(interaction, 24)

    @discord.ui.button(
        label="7 gün",
        style=discord.ButtonStyle.primary,
        custom_id="pc:history:7d",
    )
    async def yedi_gun(self, interaction, button):
        _ = button
        await self.grafiki_gonder(interaction, 168)


class GucOnayGorunumu(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.action = action

    @discord.ui.button(
        label="Onayla",
        style=discord.ButtonStyle.danger,
        custom_id="pc:confirm-power",
    )
    async def onayla(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        if not kullanima_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Yetkisiz erişim", "Bu işlem için iznin yok."),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(pc.guc_islemi_yurut, self.action)
            status_embed = await asyncio.to_thread(durum_gomulusu_olustur)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            await interaction.edit_original_response(
                embed=hata_gomulusu_olustur("İşlem başlatılamadı", str(exc)),
                view=None,
            )
            return
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="✅ İşlem onaylandı",
                description=result,
                color=discord.Color.orange(),
            ),
            view=None,
        )
        if discord_istemcisi is not None:
            try:
                await discord_istemcisi.kontrol_panelini_guncelle(status_embed)
            except (discord.DiscordException, OSError):
                logger.exception("Güç işlemi planlandıktan sonra panel güncellenemedi.")

    @discord.ui.button(
        label="Vazgeç",
        style=discord.ButtonStyle.secondary,
        custom_id="pc:cancel-confirmation",
    )
    async def vazgec(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        if not kullanima_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=hata_gomulusu_olustur("Yetkisiz erişim", "Bu işlem için iznin yok."),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="İşlem yapılmadı",
                description="Bilgisayarda herhangi bir değişiklik yapılmadı.",
                color=discord.Color.dark_grey(),
            ),
            view=None,
        )


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
        except (discord.DiscordException, OSError, RuntimeError, ValueError):
            hazirlik_durumunu_temizle()
            logger.exception(
                "Discord kontrol paneli başlatılamadı. "
                "Kanal kimliğini ve botun kanal izinlerini denetleyin."
            )
            return
        if self.panel_task is None or self.panel_task.done():
            self.panel_task = asyncio.create_task(
                self.kontrol_panelini_yenile(),
                name="pc-control-embed-refresh",
            )

    async def on_disconnect(self) -> None:
        hazirlik_durumunu_temizle()
        logger.warning("Discord kontrol botunun bağlantısı kesildi.")

    async def kontrol_panelini_hazirla(self) -> None:
        channel = self.get_channel(kontrol_kanali_kimligi)
        if channel is None:
            channel = await self.fetch_channel(kontrol_kanali_kimligi)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != sunucu_kimligi:
            raise ValueError("Yapılandırılan kontrol kanalı seçilen sunucuda bir metin kanalı değil.")

        message_id = None
        try:
            with PANEL_DOSYASI.open("r", encoding="utf-8") as panel_file:
                message_id = json.load(panel_file).get("message_id")
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError):
            logger.exception("Kayıtlı Discord kontrol paneli mesaj kimliği okunamadı.")

        if message_id:
            try:
                self.panel_message = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                logger.warning("Kayıtlı kontrol paneli mesajı silinmiş; yenisi oluşturuluyor.")
            except discord.Forbidden as exc:
                raise RuntimeError(
                    "Botun Kanalı Görüntüle, Mesaj Geçmişini Oku ve Mesaj Gönder izinlerine ihtiyacı var."
                ) from exc

        embed = await asyncio.to_thread(durum_gomulusu_olustur)
        if self.panel_message is None:
            self.panel_message = await channel.send(
                embed=embed,
                view=KontrolPaneliGorunumu(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            temp_path = PANEL_DOSYASI.with_suffix(".json.tmp")
            temp_path.write_text(
                json.dumps({"message_id": self.panel_message.id}),
                encoding="utf-8",
            )
            os.replace(temp_path, PANEL_DOSYASI)
            logger.info("Kalıcı PC kontrol Embed'i %s kanalında oluşturuldu.", kontrol_kanali_kimligi)
        else:
            await self.panel_message.edit(embed=embed, view=KontrolPaneliGorunumu())
            logger.info("%s kanalındaki kalıcı PC kontrol Embed'i geri yüklendi.", kontrol_kanali_kimligi)

    async def kontrol_panelini_guncelle(self, embed=None) -> None:
        if self.panel_message is None:
            await self.kontrol_panelini_hazirla()
        if self.panel_message is None:
            raise RuntimeError("Kalıcı Discord kontrol paneli kullanılamıyor.")
        if embed is None:
            embed = await asyncio.to_thread(durum_gomulusu_olustur)
        await self.panel_message.edit(embed=embed, view=KontrolPaneliGorunumu())

    async def kontrol_panelini_yenile(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.kontrol_panelini_guncelle()
            except discord.NotFound:
                self.panel_message = None
                try:
                    await self.kontrol_panelini_hazirla()
                except (discord.DiscordException, OSError, RuntimeError, ValueError):
                    hazirlik_durumunu_temizle()
                    logger.exception("Silinen Discord kontrol paneli yeniden oluşturulamadı.")
            except (discord.DiscordException, OSError, RuntimeError, ValueError):
                logger.exception("Discord kontrol paneli otomatik yenilenemedi.")
            await asyncio.sleep(60)


def hazirlik_durumunu_yaz() -> None:
    temp_path = HAZIRLIK_DOSYASI.with_suffix(".json.tmp")
    try:
        temp_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        os.replace(temp_path, HAZIRLIK_DOSYASI)
    finally:
        temp_path.unlink(missing_ok=True)


def hazirlik_durumunu_temizle() -> None:
    try:
        with HAZIRLIK_DOSYASI.open("r", encoding="utf-8") as ready_file:
            ready = json.load(ready_file)
        if ready.get("pid") == os.getpid():
            HAZIRLIK_DOSYASI.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError, AttributeError):
        logger.exception("Discord hazır durumu işareti temizlenemedi.")


async def botu_baslat() -> None:
    global bot_olay_dongusu, discord_istemcisi
    bot_olay_dongusu = asyncio.get_running_loop()
    discord_istemcisi = DiscordKontrolIstemcisi()
    await discord_istemcisi.start(bot_anahtari)


def botu_calistir() -> None:
    global baslangic_hatasi
    if not bot_anahtari or yetkili_kullanici_kimligi <= 0 or sunucu_kimligi <= 0 or kontrol_kanali_kimligi <= 0:
        baslangic_hatasi = "Discord bot token'ı, kullanıcı, sunucu veya kanal kimliği eksik."
        logger.error(baslangic_hatasi)
        return
    try:
        asyncio.run(botu_baslat())
    except (discord.DiscordException, OSError, RuntimeError) as exc:
        baslangic_hatasi = str(exc)
        hazirlik_durumunu_temizle()
        logger.exception("Discord kontrol botu beklenmedik biçimde durdu.")


def botu_durdur() -> None:
    if (
        discord_istemcisi is None
        or bot_olay_dongusu is None
        or discord_istemcisi.is_closed()
    ):
        return
    asyncio.run_coroutine_threadsafe(discord_istemcisi.close(), bot_olay_dongusu)
