import discord
from discord.ext import tasks, commands
import socket
import os

TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_HOST = "want-hopes.gl.at.ply.gg"
SERVER_PORT = 12696
CHANNEL_ID = 1437964841263304795

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

last_status = None

def is_server_online(host, port, timeout=5):
    """Check if the Minecraft server is online using a TCP connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    check_server.start()

@tasks.loop(minutes=1)
async def check_server():
    global last_status
    channel = bot.get_channel(CHANNEL_ID)

    if channel is None:
        print("❌ Channel not found or bot has no access.")
        return

    online = is_server_online(SERVER_HOST, SERVER_PORT)
    current_status = "online" if online else "offline"

    if current_status != last_status:
        if current_status == "online":
            await channel.send(f"🟢 **Server is ONLINE!** 🎉")
        else:
            await channel.send(f"🔴 **Server is OFFLINE!** 😢")
        last_status = current_status

bot.run(TOKEN)