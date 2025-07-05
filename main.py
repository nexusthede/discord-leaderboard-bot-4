from keep_alive import keep_alive
keep_alive()

import discord
from discord.ext import commands, tasks
import sqlite3
import os
import json

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

# Globals for channel IDs and leaderboard messages
message_channel_id = None
voice_channel_id = None
leaderboard_msgs = {}

LEADERBOARD_IDS_FILE = "leaderboard_msg_ids.json"

def save_leaderboard_msg_ids():
    global leaderboard_msgs, message_channel_id, voice_channel_id
    if 'msg' in leaderboard_msgs and 'vc' in leaderboard_msgs:
        with open(LEADERBOARD_IDS_FILE, "w") as f:
            json.dump({
                "msg_id": leaderboard_msgs['msg'].id,
                "vc_id": leaderboard_msgs['vc'].id,
                "msg_channel": message_channel_id,
                "vc_channel": voice_channel_id
            }, f)

async def load_leaderboard_msgs():
    global leaderboard_msgs, message_channel_id, voice_channel_id
    if not os.path.exists(LEADERBOARD_IDS_FILE):
        return
    with open(LEADERBOARD_IDS_FILE, "r") as f:
        data = json.load(f)
    if not data:
        return

    message_channel_id = data.get("msg_channel")
    voice_channel_id = data.get("vc_channel")
    msg_channel = bot.get_channel(int(message_channel_id)) if message_channel_id else None
    vc_channel = bot.get_channel(int(voice_channel_id)) if voice_channel_id else None

    msg_msg = None
    vc_msg = None
    try:
        if msg_channel and data.get("msg_id"):
            msg_msg = await msg_channel.fetch_message(int(data.get("msg_id")))
    except Exception:
        msg_msg = None
    try:
        if vc_channel and data.get("vc_id"):
            vc_msg = await vc_channel.fetch_message(int(data.get("vc_id")))
    except Exception:
        vc_msg = None

    if msg_msg and vc_msg:
        leaderboard_msgs['msg'] = msg_msg
        leaderboard_msgs['vc'] = vc_msg
        leaderboard_msgs['guild'] = msg_msg.guild

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
    await bot.process_commands(message)

# Admin-only commands

@bot.command(name="set messages")
@commands.has_permissions(administrator=True)
async def set_messages(ctx, channel: discord.TextChannel):
    global message_channel_id
    message_channel_id = channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('message_channel', ?)", (message_channel_id,))
    conn.commit()
    await ctx.send(f"✅ Message leaderboard will be posted in {channel.mention}")

@bot.command(name="set voice")
@commands.has_permissions(administrator=True)
async def set_voice(ctx, channel: discord.TextChannel):
    global voice_channel_id
    voice_channel_id = channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('voice_channel', ?)", (voice_channel_id,))
    conn.commit()
    await ctx.send(f"✅ Voice leaderboard will be posted in {channel.mention}")

@bot.command(name="post lbs")
@commands.has_permissions(administrator=True)
async def post_leaderboards(ctx):
    global leaderboard_msgs, message_channel_id, voice_channel_id

    c.execute("SELECT value FROM settings WHERE key = 'message_channel'")
    msg = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key = 'voice_channel'")
    vc = c.fetchone()
    if not msg or not vc:
        return await ctx.send("❌ Please run `!set messages #channel` and `!set voice #channel` first.")

    message_channel_id = int(msg[0])
    voice_channel_id = int(vc[0])
    msg_channel = bot.get_channel(message_channel_id)
    vc_channel = bot.get_channel(voice_channel_id)

    top_msg = c.execute("SELECT * FROM user_stats ORDER BY messages DESC LIMIT 10").fetchall()
    top_vc = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC LIMIT 10").fetchall()

    msg_embed = discord.Embed(title="🏆 Messages Leaderboard", description=format_leaderboard(top_msg, False, ctx.guild))
    vc_embed = discord.Embed(title="🔊 Voice Leaderboard", description=format_leaderboard(top_vc, True, ctx.guild))

    msg_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    vc_embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    msg_embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    vc_embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    msg_embed.set_footer(text="⏳ Updates every 10 minutes")
    vc_embed.set_footer(text="⏳ Updates every 10 minutes")

    msg_msg = await msg_channel.send(embed=msg_embed)
    vc_msg = await vc_channel.send(embed=vc_embed)

    leaderboard_msgs = {'msg': msg_msg, 'vc': vc_msg, 'guild': ctx.guild}

    save_leaderboard_msg_ids()

    await ctx.send("✅ Leaderboards posted and will auto-update every 10 minutes.")

# Everyone commands

@bot.command(name="update")
@commands.has_permissions(administrator=True)
async def update_leaderboard(ctx):
    if leaderboard_msgs:
        await update_now()
        await ctx.send("✅ Leaderboards updated manually.")
    else:
        await ctx.send("❌ Leaderboards not started. Use `!post lbs`.")

@bot.command(name="messages")
async def messages(ctx):
    user_id = str(ctx.author.id)
    guild = ctx.guild
    total_members = guild.member_count

    top = c.execute("SELECT * FROM user_stats ORDER BY messages DESC").fetchall()
    if not top:
        return await ctx.send("No message data yet.")

    embed = discord.Embed(title="🏆 Messages Leaderboard")

    # Top 10 users display
    top_10 = top[:10]
    embed.description = format_leaderboard(top_10, False, guild)

    # Find author's rank and messages
    ranks = {u[0]: idx+1 for idx, u in enumerate(top)}
    rank = ranks.get(user_id, None)
    messages_count = 0
    for u in top:
        if u[0] == user_id:
            messages_count = u[1]
            break

    if rank:
        embed.add_field(
            name=f"Your Rank: #{rank} • {ctx.author.display_name}",
            value=f"{messages_count} messages\nRank {rank} • {total_members} members",
            inline=False
        )

    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.set_footer(text="⏳ Updates every 10 minutes")

    await ctx.send(embed=embed)

@bot.command(name="voice")
async def voice(ctx):
    user_id = str(ctx.author.id)
    guild = ctx.guild
    total_members = guild.member_count

    top = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC").fetchall()
    if not top:
        return await ctx.send("No voice data yet.")

    embed = discord.Embed(title="🔊 Voice Leaderboard")

    # Top 10 users display
    top_10 = top[:10]
    embed.description = format_leaderboard(top_10, True, guild)

    # Find author's rank and voice seconds
    ranks = {u[0]: idx+1 for idx, u in enumerate(top)}
    rank = ranks.get(user_id, None)
    voice_seconds = 0
    for u in top:
        if u[0] == user_id:
            voice_seconds = u[2]
            break

    if rank:
        embed.add_field(
            name=f"Your Rank: #{rank} • {ctx.author.display_name}",
            value=f"{format_voice_time(voice_seconds)}\nRank {rank} • {total_members} members",
            inline=False
        )

    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.set_footer(text="⏳ Updates every 10 minutes")

    await ctx.send(embed=embed)

@tasks.loop(minutes=10)
async def update_leaderboards():
    if leaderboard_msgs:
        await update_now()

async def update_now():
    if not leaderboard_msgs:
        return
    msg = leaderboard_msgs['msg']
    vc = leaderboard_msgs['vc']
    guild = leaderboard_msgs['guild']

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
    except discord.NotFound:
        # Messages deleted? Resend and save new IDs
        msg_channel = bot.get_channel(message_channel_id)
        vc_channel = bot.get_channel(voice_channel_id)
        msg_msg = await msg_channel.send(embed=msg_embed)
        vc_msg = await vc_channel.send(embed=vc_embed)
        leaderboard_msgs['msg'] = msg_msg
        leaderboard_msgs['vc'] = vc_msg
        save_leaderboard_msg_ids()
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
