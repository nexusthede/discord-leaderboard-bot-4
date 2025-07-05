from keep_alive import keep_alive
keep_alive()

import discord
from discord.ext import commands, tasks
import sqlite3
import os

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Database setup
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

message_channel_id = None
voice_channel_id = None
leaderboard_msgs = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.change_presence(
        activity=discord.Streaming(name="I love nexus so much", url="https://twitch.tv/nexus")
    )
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
    await bot.process_commands(message)

@bot.command()
async def setupmessages(ctx):
    global message_channel_id
    message_channel_id = ctx.channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('message_channel', ?)", (message_channel_id,))
    conn.commit()
    await ctx.send("✅ Message leaderboard will be posted here.")

@bot.command
async def setupvoice(ctx):
    global voice_channel_id
    voice_channel_id = ctx.channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('voice_channel', ?)", (voice_channel_id,))
    conn.commit()
    await ctx.send("✅ Voice leaderboard will be posted here.")

@bot.command()
async def startleaderboard(ctx):
    global leaderboard_msgs
    c.execute("SELECT value FROM settings WHERE key = 'message_channel'")
    msg = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key = 'voice_channel'")
    vc = c.fetchone()
    if not msg or not vc:
        return await ctx.send("❌ Please run `!setupmessages` and `!setupvoice` first.")

    msg_channel = bot.get_channel(int(msg[0]))
    vc_channel = bot.get_channel(int(vc[0]))

    msg_embed = discord.Embed(title="🏆 Text Leaderboard", description="Loading...")
    vc_embed = discord.Embed(title="🔊 Voice Leaderboard", description="Loading...")

    msg_msg = await msg_channel.send(embed=msg_embed)
    vc_msg = await vc_channel.send(embed=vc_embed)

    leaderboard_msgs = {'msg': msg_msg, 'vc': vc_msg, 'guild': ctx.guild}

    await ctx.send("✅ Leaderboards posted and will auto-update every 10 minutes.")

@bot.command()
async def updateleaderboard(ctx):
    if leaderboard_msgs:
        await update_now()
        await ctx.send("✅ Leaderboards updated manually.")
    else:
        await ctx.send("❌ Leaderboards not started. Use `!startleaderboard`.")

@bot.command()
async def forceupdate(ctx):
    await updateleaderboard(ctx)

@bot.command()
async def messages(ctx):
    top = c.execute("SELECT * FROM user_stats ORDER BY messages DESC LIMIT 10").fetchall()
    if not top:
        return await ctx.send("No data yet.")
    embed = discord.Embed(title="🏆 Text Leaderboard")
    embed.description = format_leaderboard(top, False, ctx.guild)
    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_footer(text="⏳ Updates every 10 minutes")
    await ctx.send(embed=embed)

@bot.command()
async def voice(ctx):
    top = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC LIMIT 10").fetchall()
    if not top:
        return await ctx.send("No data yet.")
    embed = discord.Embed(title="🔊 Voice Leaderboard")
    embed.description = format_leaderboard(top, True, ctx.guild)
    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_footer(text="⏳ Updates every 10 minutes")
    await ctx.send(embed=embed)

@tasks.loop(minutes=10)
async def update_leaderboards():
    if leaderboard_msgs:
        await update_now()

async def update_now():
    msg = leaderboard_msgs['msg']
    vc = leaderboard_msgs['vc']
    guild = leaderboard_msgs['guild']
    top_msg = c.execute("SELECT * FROM user_stats ORDER BY messages DESC LIMIT 10").fetchall()
    top_vc = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC LIMIT 10").fetchall()

    msg_embed = discord.Embed(title="🏆 Text Leaderboard", description=format_leaderboard(top_msg, False, guild))
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

join_times = {}

@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    key = f"{member.guild.id}-{uid}"
    if not before.channel and after.channel:
        join_times[key] = discord.utils.utcnow()
    elif before.channel and not after.channel and key in join_times:
        seconds = (discord.utils.utcnow() - join_times[key]).total_seconds()
        del join_times[key]
        row = c.execute("SELECT * FROM user_stats WHERE user_id = ?", (uid,)).fetchone()
        if row:
            c.execute("UPDATE user_stats SET voice_seconds = voice_seconds + ? WHERE user_id = ?", (int(seconds), uid))
        else:
            c.execute("INSERT INTO user_stats (user_id, messages, voice_seconds) VALUES (?, 0, ?)", (uid, int(seconds)))
        conn.commit()

bot.run(os.getenv("TOKEN"))
