from keep_alive import keep_alive
keep_alive()

import discord
from discord.ext import commands, tasks
import sqlite3
import os
import json

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

conn = sqlite3.connect('stats.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS user_stats (
    user_id TEXT PRIMARY KEY,
    messages INTEGER DEFAULT 0,
    voice_seconds INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)''')
conn.commit()

leaderboard_msgs = {}

LEADERBOARD_FILE = "leaderboard_ids.json"

def save_leaderboard_msgs():
    if 'msg' in leaderboard_msgs and 'vc' in leaderboard_msgs:
        with open(LEADERBOARD_FILE, "w") as f:
            json.dump({
                "msg_id": leaderboard_msgs['msg'].id,
                "vc_id": leaderboard_msgs['vc'].id,
                "msg_channel": leaderboard_msgs['msg'].channel.id,
                "vc_channel": leaderboard_msgs['vc'].channel.id
            }, f)

async def load_leaderboard_msgs():
    global leaderboard_msgs
    if not os.path.exists(LEADERBOARD_FILE):
        return
    with open(LEADERBOARD_FILE, "r") as f:
        data = json.load(f)
    try:
        msg_channel = bot.get_channel(int(data["msg_channel"]))
        vc_channel = bot.get_channel(int(data["vc_channel"]))
        msg_msg = await msg_channel.fetch_message(int(data["msg_id"]))
        vc_msg = await vc_channel.fetch_message(int(data["vc_id"]))
        leaderboard_msgs = {'msg': msg_msg, 'vc': vc_msg}
        print("✅ Loaded leaderboard messages from file.")
    except Exception as e:
        print(f"Failed to load leaderboard messages: {e}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.change_presence(
        activity=discord.Streaming(name="I love nexus so much", url="https://twitch.tv/nexus")
    )
    await load_leaderboard_msgs()
    update_leaderboards.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    user_id = str(message.author.id)
    c.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE user_stats SET messages = messages + 1 WHERE user_id = ?", (user_id,))
    else:
        c.execute("INSERT INTO user_stats (user_id, messages, voice_seconds) VALUES (?, 1, 0)", (user_id,))
    conn.commit()
    print(f"📩 Counted message from {message.author} (Total messages updated).")
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    key = f"{member.guild.id}-{uid}"
    if not hasattr(bot, 'join_times'):
        bot.join_times = {}
    join_times = bot.join_times

    if not before.channel and after.channel:
        join_times[key] = discord.utils.utcnow()
        print(f"🔊 {member} joined voice channel {after.channel.name}")
    elif before.channel and not after.channel and key in join_times:
        seconds = (discord.utils.utcnow() - join_times[key]).total_seconds()
        del join_times[key]
        row = c.execute("SELECT * FROM user_stats WHERE user_id = ?", (uid,)).fetchone()
        if row:
            c.execute("UPDATE user_stats SET voice_seconds = voice_seconds + ? WHERE user_id = ?", (int(seconds), uid))
        else:
            c.execute("INSERT INTO user_stats (user_id, messages, voice_seconds) VALUES (?, 0, ?)", (uid, int(seconds)))
        conn.commit()
        print(f"🔉 {member} left voice channel {before.channel.name} after {int(seconds)} seconds.")

@bot.command()
async def setmessages(ctx):
    channel_id = ctx.channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('message_channel', ?)", (channel_id,))
    conn.commit()
    await ctx.send(f"✅ Message leaderboard will be posted in {ctx.channel.mention}")

@bot.command()
async def setvoice(ctx):
    channel_id = ctx.channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('voice_channel', ?)", (channel_id,))
    conn.commit()
    await ctx.send(f"✅ Voice leaderboard will be posted in {ctx.channel.mention}")

@bot.command()
async def postlbs(ctx):
    c.execute("SELECT value FROM settings WHERE key = 'message_channel'")
    msg = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key = 'voice_channel'")
    vc = c.fetchone()

    if not msg or not vc:
        return await ctx.send("❌ Please run `!setmessages` and `!setvoice` first.")

    try:
        message_channel_id = int(msg[0])
        voice_channel_id = int(vc[0])
        msg_channel = bot.get_channel(message_channel_id)
        vc_channel = bot.get_channel(voice_channel_id)
        if msg_channel is None or vc_channel is None:
            return await ctx.send("❌ One or both leaderboard channels not found. Make sure the bot has access.")
    except Exception:
        return await ctx.send("❌ Invalid channel IDs in settings. Please reset them.")

    top_msg = c.execute("SELECT * FROM user_stats ORDER BY messages DESC LIMIT 10").fetchall()
    top_vc = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC LIMIT 10").fetchall()

    guild = ctx.guild

    msg_embed = discord.Embed(title="🏆 Messages Leaderboard", description=format_leaderboard(top_msg, False, guild))
    vc_embed = discord.Embed(title="🔊 Voice Leaderboard", description=format_leaderboard(top_vc, True, guild))

    msg_embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    vc_embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    msg_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    vc_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    msg_embed.set_footer(text="⏳ Updates every 10 minutes")
    vc_embed.set_footer(text="⏳ Updates every 10 minutes")

    msg_msg = await msg_channel.send(embed=msg_embed)
    vc_msg = await vc_channel.send(embed=vc_embed)

    leaderboard_msgs['msg'] = msg_msg
    leaderboard_msgs['vc'] = vc_msg
    save_leaderboard_msgs()

    await ctx.send("✅ Leaderboards posted and will auto-update every 10 minutes.")
    print("✅ Leaderboards posted.")

@bot.command()
async def update(ctx):
    if leaderboard_msgs:
        await update_now()
        await ctx.send("✅ Leaderboards updated manually.")
        print("🔄 Leaderboards updated manually via command.")
    else:
        await ctx.send("❌ Leaderboards are not started. Use `!postlbs` first.")

@tasks.loop(minutes=10)
async def update_leaderboards():
    if leaderboard_msgs:
        await update_now()
        print("🔄 Leaderboards auto-updated.")

async def update_now():
    if not leaderboard_msgs:
        return
    msg = leaderboard_msgs['msg']
    vc = leaderboard_msgs['vc']

    guild = bot.get_guild(msg.guild.id)
    if guild is None:
        print("Guild not found!")
        return

    c.execute("SELECT value FROM settings WHERE key = 'message_channel'")
    msg_channel_id = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key = 'voice_channel'")
    vc_channel_id = c.fetchone()

    if not msg_channel_id or not vc_channel_id:
        print("Leaderboard channels not set in DB!")
        return

    msg_channel = bot.get_channel(int(msg_channel_id[0]))
    vc_channel = bot.get_channel(int(vc_channel_id[0]))

    if msg_channel is None or vc_channel is None:
        print("Leaderboard channels not found by bot!")
        return

    top_msg = c.execute("SELECT * FROM user_stats ORDER BY messages DESC LIMIT 10").fetchall()
    top_vc = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC LIMIT 10").fetchall()

    msg_embed = discord.Embed(title="🏆 Messages Leaderboard", description=format_leaderboard(top_msg, False, guild))
    vc_embed = discord.Embed(title="🔊 Voice Leaderboard", description=format_leaderboard(top_vc, True, guild))

    msg_embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    vc_embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    msg_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    vc_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    msg_embed.set_footer(text="⏳ Updates every 10 minutes")
    vc_embed.set_footer(text="⏳ Updates every 10 minutes")

    try:
        await msg.edit(embed=msg_embed)
        await vc.edit(embed=vc_embed)
        print("✅ Leaderboard embeds updated successfully.")
    except discord.NotFound:
        msg_msg = await msg_channel.send(embed=msg_embed)
        vc_msg = await vc_channel.send(embed=vc_embed)
        leaderboard_msgs['msg'] = msg_msg
        leaderboard_msgs['vc'] = vc_msg
        save_leaderboard_msgs()
        print("⚠️ Leaderboard messages missing, sent new ones.")
    except discord.HTTPException as e:
        print(f"Embed edit failed: {e}")

def format_leaderboard(users, is_voice, guild):
    medals = ['🥇', '🥈', '🥉']
    lines = []
    for i, u in enumerate(users):
        member = guild.get_member(int(u[0]))
        if not member:
            continue
        value = format_voice_time(u[2]) if is_voice else f"{u[1]} msgs"
        rank = medals[i] if i < 3 else f"#{i + 1}"
        lines.append(f"{rank} — {member.mention} • {value}")
    return "\n".join(lines)

def format_voice_time(seconds):
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{d}d {h}h {m}m {s}s"

bot.run(os.getenv("TOKEN"))
