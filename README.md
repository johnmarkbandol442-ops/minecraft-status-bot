# Minecraft Server Status Discord Bot

What I did:
- Implemented a Discord bot that properly detects Java and Bedrock servers (Bedrock via mcstatus UDP handshake).
- Added debounce (stable-state) and rate-limiting to avoid spamming when the server flaps.
- Added optional rich embeds and environment-based configuration.
- Provided a Dockerfile for easy deployment.

Quick start (local)
1. Install dependencies:
   pip install discord.py mcstatus

2. Set environment variables:
   - DISCORD_TOKEN (required)
   - DISCORD_CHANNEL_ID (required)
   - MC_SERVER_HOST (default: 23.ip.gl.ply.gg)
   - MC_SERVER_PORT (default: 12696)
   - MC_PROTOCOL (auto/java/bedrock) — default 'auto'
   - CHECK_INTERVAL (seconds, default 60)
   - STABLE_THRESHOLD (default 2)
   - RATE_LIMIT_SECONDS (default 300)
   - USE_EMBED (true/false, default true)

3. Run:
   python bot.py

Docker
1. Build:
   docker build -t mc-status-bot .

2. Run (example):
   docker run -e DISCORD_TOKEN=... -e DISCORD_CHANNEL_ID=1437964841263304795 \
     -e MC_SERVER_HOST=23.ip.gl.ply.gg -e MC_SERVER_PORT=12696 \
     mc-status-bot

Notes & debugging tips
- For Bedrock you MUST have mcstatus available (the bot warns if missing).
- Ensure your Playit.gg tunnel forwards UDP for Bedrock and the host:port match.
- Use the `!server` command in Discord to perform a manual check.
- If the bot still reports offline, run this on your machine:
  python -c "from mcstatus import BedrockServer; print(BedrockServer('want-hopes.gl.at.ply.gg', 12696).status())"
  Paste the output into the chat and I can help diagnose further.

If you want, I can:
- Add an admin-only command to change settings at runtime (channel, protocol, threshold).
- Add persistent state (e.g., last announced status) in a small file or Redis so restarts don't re-announce.
- Add unit tests or GitHub Actions for CI.
