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


APP_NAME = "PCActivityMonitor"
STATE_DIR = Path(os.environ["APPDATA"]) / APP_NAME
CONFIG_FILE = STATE_DIR / "config.json"
PANEL_FILE = STATE_DIR / "discord_panel.json"
READY_FILE = STATE_DIR / "discord_ready.json"
LOG_FILE = STATE_DIR / "discord.log"
logger = logging.getLogger("pc_discord_control")
logger.setLevel(logging.INFO)
logger.addHandler(
    RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
)

with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
    config = json.load(config_file)

BOT_TOKEN = config.get("BOT_TOKEN")
ALLOWED_USER_ID = int(config.get("ALLOWED_USER_ID", 0))
GUILD_ID = int(config.get("GUILD_ID", 0))
CHANNEL_ID = int(config.get("CHANNEL_ID", 0))
bot_loop = None
bot_client = None
startup_error = None


def allowed(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.id == ALLOWED_USER_ID
        and interaction.guild_id == GUILD_ID
        and interaction.channel_id == CHANNEL_ID
    )


def make_status_embed(status=None):
    status = status or pc.collect_status()
    now = datetime.now().astimezone()
    pending = status["pending_action"]
    if pending == "restart":
        power_state = f"Yeniden başlatma planlandı · {status['pending_seconds']} sn kaldı"
    elif pending == "shutdown":
        power_state = f"Kapatma planlandı · {status['pending_seconds']} sn kaldı"
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
            f"**Ad:** `{status['hostname']}`\n"
            f"**Windows hesabı:** `{status['username']}`\n"
            f"**Durum:** 🟢 Çevrimiçi"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚙️ İşlemci",
        value=(
            f"**Kullanım:** {status['cpu']}%\n"
            f"**Model:** {status['cpu_model']}\n"
            f"**Çekirdek / izlek:** {status['cpu_cores']} / {status['cpu_threads']}\n"
            f"**Anlık frekans:** {status['cpu_frequency_mhz'] or 'N/A'} MHz"
        ),
        inline=True,
    )
    embed.add_field(
        name="🧠 Bellek",
        value=(
            f"**Kullanım:** {status['ram']}% "
            f"({status['ram_used_gb']} / {status['ram_total_gb']} GB)\n"
            f"**Kullanılabilir:** {status['ram_available_gb']} GB"
        ),
        inline=True,
    )
    embed.add_field(
        name="💽 Sistem diski",
        value=(
            f"**Kullanım:** {status['disk_used']}%\n"
            f"**Boş alan:** {status['disk_free_gb']} / {status['disk_total_gb']} GB"
        ),
        inline=True,
    )
    embed.add_field(
        name="⏱️ Sistem",
        value=(
            f"**Çalışma süresi:** {pc.format_duration(status['uptime_seconds'])}\n"
            f"**Son açılış:** {status['boot_time']}\n"
            f"**İşletim sistemi:** {status['os_name']}"
        ),
        inline=True,
    )
    embed.add_field(
        name="🔋 Pil",
        value=status["battery"],
        inline=True,
    )
    applications = status["applications"]
    application_lines = applications[:12]
    if len(applications) > len(application_lines):
        application_lines.append(f"+{len(applications) - len(application_lines)} uygulama daha")
    if status["unavailable_applications"]:
        application_lines.append(
            f"{status['unavailable_applications']} uygulamanın adı okunamadı"
        )
    if status["applications_error"]:
        application_lines = [status["applications_error"]]
    embed.add_field(
        name=f"🪟 Açık uygulamalar ({len(applications)})",
        value="\n".join(
            application_lines
            if status["applications_error"]
            else [f"• `{name[:48]}`" for name in application_lines]
        )
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


def make_error_embed(title, message):
    return discord.Embed(
        title=title,
        description=message,
        color=discord.Color.red(),
        timestamp=datetime.now().astimezone(),
    )


class ControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if allowed(interaction):
            return True
        logger.warning(
            "Rejected control-panel interaction from user %s in guild %s channel %s.",
            interaction.user.id,
            interaction.guild_id,
            interaction.channel_id,
        )
        await interaction.response.send_message(
            embed=make_error_embed(
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
    async def refresh_status(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        try:
            embed = await asyncio.to_thread(make_status_embed)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            logger.exception("Could not refresh the PC control embed.")
            await interaction.response.send_message(
                embed=make_error_embed("Durum alınamadı", str(exc)),
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
    async def screenshot(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            image = await asyncio.to_thread(pc.capture_screenshot)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.exception("Could not capture screen for the Discord control panel.")
            await interaction.followup.send(
                embed=make_error_embed("Ekran görüntüsü alınamadı", str(exc)),
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
    async def request_restart(
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
            view=PowerConfirmationView("restart"),
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
    async def request_shutdown(
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
            view=PowerConfirmationView("shutdown"),
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
    async def cancel_power_action(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        await interaction.response.defer()
        try:
            message = await asyncio.to_thread(pc.run_power_action, "cancel")
            embed = await asyncio.to_thread(make_status_embed)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            await interaction.followup.send(
                embed=make_error_embed("İşlem iptal edilemedi", str(exc)),
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
    async def show_help(
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
                "Açık uygulamaların adları ve isteğe bağlı ekran görüntüsü Discord üzerinden "
                "iletilir; pencere başlıkları alınmaz. Bot token'ını paylaşma; bu kanalı özel tut."
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


class PowerConfirmationView(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.action = action

    @discord.ui.button(
        label="Onayla",
        style=discord.ButtonStyle.danger,
        custom_id="pc:confirm-power",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        if not allowed(interaction):
            await interaction.response.send_message(
                embed=make_error_embed("Yetkisiz erişim", "Bu işlem için iznin yok."),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(pc.run_power_action, self.action)
            status_embed = await asyncio.to_thread(make_status_embed)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            await interaction.edit_original_response(
                embed=make_error_embed("İşlem başlatılamadı", str(exc)),
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
        if bot_client is not None:
            try:
                await bot_client.update_control_panel(status_embed)
            except (discord.DiscordException, OSError):
                logger.exception("Could not update panel after scheduling power action.")

    @discord.ui.button(
        label="Vazgeç",
        style=discord.ButtonStyle.secondary,
        custom_id="pc:cancel-confirmation",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        _ = button
        if not allowed(interaction):
            await interaction.response.send_message(
                embed=make_error_embed("Yetkisiz erişim", "Bu işlem için iznin yok."),
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


class PCControlClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.panel_message: discord.Message | None = None
        self.panel_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self.add_view(ControlPanelView())
        self.tree.clear_commands(guild=discord.Object(id=GUILD_ID))
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))

    async def on_ready(self) -> None:
        logger.info("Discord control bot is ready as %s.", self.user)
        try:
            await self.ensure_control_panel()
            publish_ready()
        except (discord.DiscordException, OSError, RuntimeError, ValueError):
            clear_ready()
            logger.exception(
                "Could not initialize the Discord control panel. "
                "Check channel ID and bot channel permissions."
            )
            return
        if self.panel_task is None or self.panel_task.done():
            self.panel_task = asyncio.create_task(
                self.refresh_control_panel(),
                name="pc-control-embed-refresh",
            )

    async def on_disconnect(self) -> None:
        clear_ready()
        logger.warning("Discord control bot disconnected.")

    async def ensure_control_panel(self) -> None:
        channel = self.get_channel(CHANNEL_ID)
        if channel is None:
            channel = await self.fetch_channel(CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
            raise ValueError("The configured panel channel is not a text channel in the selected guild.")

        message_id = None
        try:
            with PANEL_FILE.open("r", encoding="utf-8") as panel_file:
                message_id = json.load(panel_file).get("message_id")
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError):
            logger.exception("Could not read the saved Discord control-panel message ID.")

        if message_id:
            try:
                self.panel_message = await channel.fetch_message(int(message_id))
            except discord.NotFound:
                logger.warning("Saved control-panel message was deleted; creating a new one.")
            except discord.Forbidden as exc:
                raise RuntimeError(
                    "Bot needs View Channel, Read Message History, and Send Messages."
                ) from exc

        embed = await asyncio.to_thread(make_status_embed)
        if self.panel_message is None:
            self.panel_message = await channel.send(
                embed=embed,
                view=ControlPanelView(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            temp_path = PANEL_FILE.with_suffix(".json.tmp")
            temp_path.write_text(
                json.dumps({"message_id": self.panel_message.id}),
                encoding="utf-8",
            )
            os.replace(temp_path, PANEL_FILE)
            logger.info("Created the persistent PC control embed in channel %s.", CHANNEL_ID)
        else:
            await self.panel_message.edit(embed=embed, view=ControlPanelView())
            logger.info("Restored the persistent PC control embed in channel %s.", CHANNEL_ID)

    async def update_control_panel(self, embed=None) -> None:
        if self.panel_message is None:
            await self.ensure_control_panel()
        if self.panel_message is None:
            raise RuntimeError("The persistent Discord control panel is unavailable.")
        if embed is None:
            embed = await asyncio.to_thread(make_status_embed)
        await self.panel_message.edit(embed=embed, view=ControlPanelView())

    async def refresh_control_panel(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.update_control_panel()
            except discord.NotFound:
                self.panel_message = None
                try:
                    await self.ensure_control_panel()
                except (discord.DiscordException, OSError, RuntimeError, ValueError):
                    clear_ready()
                    logger.exception("Could not recreate deleted Discord control panel.")
            except (discord.DiscordException, OSError, RuntimeError, ValueError):
                logger.exception("Automatic Discord control-panel refresh failed.")
            await asyncio.sleep(60)


def publish_ready() -> None:
    temp_path = READY_FILE.with_suffix(".json.tmp")
    try:
        temp_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        os.replace(temp_path, READY_FILE)
    finally:
        temp_path.unlink(missing_ok=True)


def clear_ready() -> None:
    try:
        with READY_FILE.open("r", encoding="utf-8") as ready_file:
            ready = json.load(ready_file)
        if ready.get("pid") == os.getpid():
            READY_FILE.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError, AttributeError):
        logger.exception("Could not clear the Discord readiness marker.")


async def start_bot() -> None:
    global bot_loop, bot_client
    bot_loop = asyncio.get_running_loop()
    bot_client = PCControlClient()
    await bot_client.start(BOT_TOKEN)


def run_bot() -> None:
    global startup_error
    if not BOT_TOKEN or ALLOWED_USER_ID <= 0 or GUILD_ID <= 0 or CHANNEL_ID <= 0:
        startup_error = "Discord bot token, user ID, guild ID, or channel ID is missing."
        logger.error(startup_error)
        return
    try:
        asyncio.run(start_bot())
    except (discord.DiscordException, OSError, RuntimeError) as exc:
        startup_error = str(exc)
        clear_ready()
        logger.exception("Discord control bot stopped unexpectedly.")


def stop_bot() -> None:
    if bot_client is None or bot_loop is None or bot_client.is_closed():
        return
    asyncio.run_coroutine_threadsafe(bot_client.close(), bot_loop)
