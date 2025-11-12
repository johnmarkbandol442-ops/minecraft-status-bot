import discord
from discord.ext import tasks, commands
from mcstatus import BedrockServer
import os

TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_IP = "want-hopes.gl.at.ply.gg:12696"
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

    try:
        server = BedrockServer.lookup(SERVER_IP)
        status = server.status()
        current_status = "online"
    except:
        current_status = "offline"

    if current_status != last_status:
        if current_status == "online":
            await channel.send(f"🟢 **Server is ONLINE!** 🎉 {status.players_online} player(s) online.")
        else:
            await channel.send("🔴 **Server is OFFLINE!** 😢")
        last_status = current_status

bot.run(TOKEN)