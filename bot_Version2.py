import asyncio
import logging
import os
from typing import Optional, Tuple, Any

import discord
from discord.ext import tasks, commands
from mcstatus import BedrockServer

# Configuration
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_IP = "want-hopes.gl.at.ply.gg:12696"
CHANNEL_ID = 1437964841263304795  # int

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("minecraft-status-bot")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

last_status: Optional[str] = None


@bot.event
async def on_ready():
    if not TOKEN:
        logger.error("DISCORD_TOKEN is not set. Exiting.")
        await bot.close()
        return

    logger.info("✅ Logged in as %s (id=%s)", bot.user, bot.user.id)
    if not check_server.is_running():
        check_server.start()


async def _get_channel(channel_id: int) -> Optional[discord.abc.Messageable]:
    """
    Try to get channel from cache, otherwise fetch it from API.
    """
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            logger.exception("Failed to fetch channel %s", channel_id)
            return None
    return channel


def _query_server(server_ip: str) -> Tuple[bool, Optional[int], Any]:
    """
    Blocking call to query the server using mcstatus.
    This function is run in a thread to avoid blocking the event loop.
    Returns (online: bool, players: int or None, raw_status_or_exception)
    """
    try:
        server = BedrockServer.lookup(server_ip)
        status = server.status()
        players = getattr(status, "players_online", None)
        if players is None:
            players_obj = getattr(status, "players", None)
            if players_obj and hasattr(players_obj, "online"):
                players = players_obj.online
        # Ensure integer if possible
        try:
            players = int(players) if players is not None else None
        except Exception:
            players = None
        return True, players, status
    except Exception as e:
        return False, None, e


@tasks.loop(minutes=1)
async def check_server():
    """
    Periodically check the Bedrock server and post a message when its status changes.
    """
    global last_status

    await bot.wait_until_ready()

    channel = await _get_channel(CHANNEL_ID)
    if channel is None:
        logger.warning("Channel %s not available; skipping this check.", CHANNEL_ID)
        return

    try:
        online, players, raw = await asyncio.to_thread(_query_server, SERVER_IP)
    except Exception:
        logger.exception("Unexpected error querying server")
        online = False
        players = None
        raw = None

    current_status = "online" if online else "offline"

    if current_status != last_status:
        try:
            if current_status == "online":
                player_text = f" {players} player(s) online." if players is not None else ""
                await channel.send(f"🟢 **Server is ONLINE!** 🎉{player_text}")
                logger.info("Sent ONLINE notification (players=%s).", players)
            else:
                await channel.send("🔴 **Server is OFFLINE!** 😢")
                logger.info("Sent OFFLINE notification.")
        except Exception:
            logger.exception("Failed to send message to channel %s", CHANNEL_ID)

        last_status = current_status
    else:
        logger.debug("No status change: %s", current_status)


if __name__ == "__main__":
    if not TOKEN:
        logger.error(
            "Missing DISCORD_TOKEN environment variable. Set DISCORD_TOKEN and restart the bot."
        )
        raise SystemExit(1)

    try:
        bot.run(TOKEN)
    except Exception:
        logger.exception("Bot terminated with an exception.")