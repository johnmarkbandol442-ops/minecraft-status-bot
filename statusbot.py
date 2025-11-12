import discord
from discord.ext import tasks, commands
from mcstatus import BedrockServer
import os

TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_HOST = "want-hopes.gl.at.ply.gg"
SERVER_PORT = 12696
CHANNEL_ID = 1437964841263304795

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

last_status = None

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

    try:
        server = BedrockServer((SERVER_HOST, SERVER_PORT))
        status = server.status()
        current_status = "online"
    except Exception as e:
        print(f"Error checking server: {e}")
        current_status = "offline"

    if current_status != last_status:
        if current_status == "online":
            await channel.send(f"🟢 **Server is ONLINE!** 🎉 {status.players_online} player(s) online.")
        else:
            await channel.send("🔴 **Server is OFFLINE!** 😢")
        last_status = current_status

bot.run(TOKEN)