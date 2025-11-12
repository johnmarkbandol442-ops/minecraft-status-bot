#!/usr/bin/env python3
"""
Discord server-status bot with Bedrock/Java support, debounce, rate-limit, and optional embeds.

Environment variables:
- DISCORD_TOKEN (required)
- DISCORD_CHANNEL_ID (required) — numeric channel ID
- MC_SERVER_HOST (default: want-hopes.gl.at.ply.gg)
- MC_SERVER_PORT (default: 12696)
- MC_PROTOCOL (default: auto) — one of: auto, java, bedrock
- CHECK_INTERVAL (seconds, default: 60)
- STABLE_THRESHOLD (how many consecutive same results before announcing, default: 2)
- RATE_LIMIT_SECONDS (minimum seconds between announcements, default: 300)
- USE_EMBED (true/false, default: true)
- LOG_LEVEL (INFO/DEBUG, default: INFO)
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
import typing

import discord
from discord.ext import tasks, commands

# Optional mcstatus import
try:
    from mcstatus import JavaServer, BedrockServer
    _MCSTATUS_AVAILABLE = True
except Exception:
    JavaServer = None
    BedrockServer = None
    _MCSTATUS_AVAILABLE = False

# Config from env
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN environment variable is required")

def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v and v.isdigit() else default

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")

CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1437964841263304795"))
MC_SERVER_HOST = os.getenv("MC_SERVER_HOST", "want-hopes.gl.at.ply.gg")
MC_SERVER_PORT = int(os.getenv("MC_SERVER_PORT", "12696"))
MC_PROTOCOL = os.getenv("MC_PROTOCOL", "auto").lower()  # auto/java/bedrock
CHECK_INTERVAL = _env_int("CHECK_INTERVAL", 60)
STABLE_THRESHOLD = _env_int("STABLE_THRESHOLD", 2)
RATE_LIMIT_SECONDS = _env_int("RATE_LIMIT_SECONDS", 300)
USE_EMBED = _env_bool("USE_EMBED", True)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("mc-status-bot")

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# State
_last_status: typing.Optional[str] = None  # "online" or "offline"
_stable_count: int = 0
_last_announce: typing.Optional[datetime] = None
_last_details: typing.Optional[dict] = None


async def tcp_port_open(host: str, port: int, timeout: float = 5.0) -> bool:
    """Simple asyncio TCP connect check (used as Java fallback)."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception as e:
        log.debug("TCP check failed for %s:%s → %s", host, port, e)
        return False


async def query_java(host: str, port: int, timeout: float = 5.0) -> dict:
    """Query Java edition. Prefer mcstatus; fallback to TCP port test."""
    if _MCSTATUS_AVAILABLE and JavaServer is not None:
        try:
            server = JavaServer(host, port)
            loop = asyncio.get_running_loop()
            status = await loop.run_in_executor(None, lambda: server.status(timeout=timeout))
            players = getattr(status.players, "online", None)
            max_players = getattr(status.players, "max", None)
            motd = getattr(status, "description", None)
            latency = getattr(status, "latency", None)
            return {"available": True, "players_online": players, "max_players": max_players, "motd": motd, "latency_ms": latency}
        except Exception as e:
            log.debug("mcstatus Java query failed: %s", e)
            # fall through to TCP check
    # Fallback: simple TCP check
    ok = await tcp_port_open(host, port, timeout=timeout)
    return {"available": ok, "players_online": None, "max_players": None, "motd": None, "latency_ms": None}


async def query_bedrock(host: str, port: int, timeout: float = 5.0) -> dict:
    """Query Bedrock edition (requires mcstatus)."""
    if not (_MCSTATUS_AVAILABLE and BedrockServer is not None):
        return {"available": False, "error": "mcstatus not installed (required for Bedrock UDP checks)"}
    try:
        server = BedrockServer(host, port)
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(None, lambda: server.status(timeout=timeout))
        # mcstatus Bedrock status object fields can vary
        players = getattr(status, "players_online", None) or getattr(status, "players", None)
        max_players = getattr(status, "players_max", None) or getattr(status, "max_players", None)
        motd = getattr(status, "motd", None) or getattr(status, "description", None)
        latency = getattr(status, "latency", None)
        return {"available": True, "players_online": players, "max_players": max_players, "motd": motd, "latency_ms": latency}
    except Exception as e:
        log.debug("mcstatus Bedrock query failed: %s", e)
        return {"available": False, "error": str(e)}


async def get_status(protocol: str) -> dict:
    """Return structured status dict based on protocol choice (auto/java/bedrock)."""
    # Protocol resolution: auto attempt Bedrock then Java (or use configured)
    if protocol == "auto":
        # Prefer Bedrock check first (if mcstatus available); if it says available return it.
        if _MCSTATUS_AVAILABLE and BedrockServer is not None:
            res = await query_bedrock(MC_SERVER_HOST, MC_SERVER_PORT)
            if res.get("available"):
                return {"edition": "bedrock", **res}
        # Try Java
        res = await query_java(MC_SERVER_HOST, MC_SERVER_PORT)
        if res.get("available"):
            return {"edition": "java", **res}
        # default to Bedrock error if no success and mcstatus available for bedrock
        # Return last result with edition guessed by mcstatus availability
        guessed = "bedrock" if (_MCSTATUS_AVAILABLE and BedrockServer is not None) else "java"
        return {"edition": guessed, **res}
    elif protocol == "java":
        res = await query_java(MC_SERVER_HOST, MC_SERVER_PORT)
        return {"edition": "java", **res}
    elif protocol == "bedrock":
        res = await query_bedrock(MC_SERVER_HOST, MC_SERVER_PORT)
        return {"edition": "bedrock", **res}
    else:
        raise ValueError("Unsupported protocol: " + protocol)


def make_embed(online: bool, details: dict) -> discord.Embed:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    color = discord.Color.green() if online else discord.Color.red()
    title = "Server is ONLINE ✅" if online else "Server is OFFLINE ❌"
    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="Host", value=f"{MC_SERVER_HOST}:{MC_SERVER_PORT}", inline=True)
    embed.add_field(name="Edition", value=details.get("edition", "unknown"), inline=True)
    embed.add_field(name="Checked", value=now, inline=False)
    if online:
        players = details.get("players_online")
        maxp = details.get("max_players")
        if players is not None or maxp is not None:
            embed.add_field(name="Players", value=f"{players}/{maxp}" if maxp else f"{players}", inline=True)
        motd = details.get("motd")
        if motd:
            embed.add_field(name="MOTD", value=str(motd), inline=False)
        latency = details.get("latency_ms")
        if latency is not None:
            embed.add_field(name="Ping (ms)", value=str(latency), inline=True)
    else:
        err = details.get("error")
        if err:
            embed.add_field(name="Error", value=str(err), inline=False)
    footer_text = f"Debounce: {STABLE_THRESHOLD} checks • RateLimit: {RATE_LIMIT_SECONDS}s"
    embed.set_footer(text=footer_text)
    return embed


@bot.event
async def on_ready():
    log.info("Logged in as %s (ID:%s) — polling %s:%s (%s)", bot.user, bot.user.id, MC_SERVER_HOST, MC_SERVER_PORT, MC_PROTOCOL)
    check_server.start()


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_server():
    global _last_status, _stable_count, _last_announce, _last_details
    await bot.wait_until_ready()

    # Resolve channel
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(CHANNEL_ID)
        except Exception as e:
            log.error("Cannot fetch channel %s: %s", CHANNEL_ID, e)
            return

    # Get status
    try:
        details = await get_status(MC_PROTOCOL)
    except Exception as e:
        log.exception("Status check failed: %s", e)
        details = {"available": False, "error": str(e), "edition": "unknown"}

    online = bool(details.get("available"))
    current_status = "online" if online else "offline"

    # Debounce: require STABLE_THRESHOLD consecutive identical results
    if current_status == _last_status:
        _stable_count += 1
    else:
        _stable_count = 1  # first time we see this new state
    log.debug("Status=%s stable_count=%d", current_status, _stable_count)

    # Only announce if stable enough
    if _stable_count >= STABLE_THRESHOLD:
        now = datetime.utcnow()
        # Rate limit announcements
        if _last_announce and (now - _last_announce).total_seconds() < RATE_LIMIT_SECONDS:
            log.info("Announcement suppressed by rate limit (last announce %s)", _last_announce.isoformat())
        else:
            # Announce only when status truly changed (different from last announced state)
            if current_status != (_last_details.get("announced_status") if _last_details else None):
                try:
                    if USE_EMBED:
                        embed = make_embed(online, {**details, "announced_status": current_status})
                        await channel.send(embed=embed)
                    else:
                        ts = now.strftime("%Y-%m-%d %H:%M:%S UTC")
                        if online:
                            txt = f"🟢 **Server is ONLINE!** ({details.get('edition')})\nHost: {MC_SERVER_HOST}:{MC_SERVER_PORT}\nTime: {ts}"
                            players = details.get("players_online")
                            maxp = details.get("max_players")
                            if players is not None or maxp is not None:
                                txt += f"\nPlayers: {players}/{maxp}"
                            motd = details.get("motd")
                            if motd:
                                txt += f"\nMOTD: {motd}"
                        else:
                            err = details.get("error")
                            txt = f"🔴 **Server is OFFLINE!**\nHost: {MC_SERVER_HOST}:{MC_SERVER_PORT}\nTime: {ts}"
                            if err:
                                txt += f"\nError: {err}"
                        await channel.send(txt)
                    _last_announce = now
                    log.info("Announced status %s to channel %s", current_status, CHANNEL_ID)
                    # mark announced status in last_details so that repeated announcements don't post
                    _last_details = {"announced_status": current_status, **details}
                except discord.Forbidden:
                    log.error("Missing permission to send in channel %s", CHANNEL_ID)
                except Exception:
                    log.exception("Failed to send announcement")
            else:
                log.debug("Status stable but already announced: %s", current_status)
    else:
        log.debug("Status not stable enough to announce (have %d need %d)", _stable_count, STABLE_THRESHOLD)

    _last_status = current_status


@check_server.before_loop
async def before_check():
    log.info("Waiting until bot is ready before starting checks")
    await bot.wait_until_ready()


@bot.command(name="server")
async def cmd_server(ctx):
    """Manual command to immediately check the server and print status."""
    await ctx.trigger_typing()
    try:
        details = await get_status(MC_PROTOCOL)
    except Exception as e:
        details = {"available": False, "error": str(e), "edition": "unknown"}
    online = bool(details.get("available"))
    if USE_EMBED:
        embed = make_embed(online, details)
        await ctx.send(embed=embed)
    else:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        if online:
            msg = f"🟢 Server is ONLINE! ({details.get('edition')})\nHost: {MC_SERVER_HOST}:{MC_SERVER_PORT}\nTime: {ts}"
            players = details.get("players_online")
            maxp = details.get("max_players")
            if players is not None or maxp is not None:
                msg += f"\nPlayers: {players}/{maxp}"
            motd = details.get("motd")
            if motd:
                msg += f"\nMOTD: {motd}"
        else:
            msg = "🔴 Server is OFFLINE."
            if details.get("error"):
                msg += f"\nError: {details.get('error')}"
        await ctx.send(msg)


if __name__ == "__main__":
    if MC_PROTOCOL == "bedrock" and not (_MCSTATUS_AVAILABLE and BedrockServer is not None):
        log.warning("mcstatus package is required for Bedrock checks. Install with: pip install mcstatus")
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        log.info("Shutting down by user request")
    except Exception:
        log.exception("Bot terminated unexpectedly")