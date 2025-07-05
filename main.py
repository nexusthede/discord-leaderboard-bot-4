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

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

@bot.command(name='setmessages')
@is_admin()
async def set_messages(ctx):
    global message_channel_id
    message_channel_id = ctx.channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('message_channel', ?)", (message_channel_id,))
    conn.commit()
    await ctx.send(f"✅ Message leaderboard will be posted in {ctx.channel.mention}")

@bot.command(name='setvoice')
@is_admin()
async def set_voice(ctx):
    global voice_channel_id
    voice_channel_id = ctx.channel.id
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('voice_channel', ?)", (voice_channel_id,))
    conn.commit()
    await ctx.send(f"✅ Voice leaderboard will be posted in {ctx.channel.mention}")

@bot.command(name='postlbs')
@is_admin()
async def post_leaderboards(ctx):
    global leaderboard_msgs, message_channel_id, voice_channel_id

    c.execute("SELECT value FROM settings WHERE key = 'message_channel'")
    msg = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key = 'voice_channel'")
    vc = c.fetchone()
    if not msg or not vc:
        return await ctx.send("❌ Please run `!setmessages` and `!setvoice` first.")

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

@bot.command(name='update')
async def update_leaderboard(ctx):
    if leaderboard_msgs:
        await update_now()
        await ctx.send("✅ Leaderboards updated manually.")
    else:
        await ctx.send("❌ Leaderboards not started. Use `!postlbs`.")

@bot.command(name='messages')
async def messages(ctx):
    top = c.execute("SELECT * FROM user_stats ORDER BY messages DESC LIMIT 10").fetchall()
    if not top:
        return await ctx.send("No data yet.")

    embed = discord.Embed(title="🏆 Messages Leaderboard")
    embed.description = format_leaderboard(top, False, ctx.guild)

    user_id = str(ctx.author.id)
    all_users = c.execute("SELECT user_id FROM user_stats ORDER BY messages DESC").fetchall()
    rank = None
    for i, u in enumerate(all_users, start=1):
        if u[0] == user_id:
            rank = i
            break

    user_data = c.execute("SELECT messages FROM user_stats WHERE user_id = ?", (user_id,)).fetchone()
    user_msgs = user_data[0] if user_data else 0
    total_members = ctx.guild.member_count

    if rank:
        embed.add_field(
            name=f"Your Rank: #{rank} • {ctx.author.display_name}",
            value=f"{user_msgs:,} msgs\n# {rank} • {total_members} members",
            inline=False
        )
    else:
        embed.add_field(
            name="Your Rank: Unranked",
            value=f"0 msgs\n# 0 • {total_members} members",
            inline=False
        )

    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_footer(text="⏳ Updates every 10 minutes")

    await ctx.send(embed=embed)

    # Plain-text output below embed
    lines = []
    lines.append("🏆 Messages Leaderboard\n")
    medals = ['🥇', '🥈', '🥉']
    for i, u in enumerate(top):
        member = ctx.guild.get_member(int(u[0]))
        if not member:
            continue
        rank_display = medals[i] if i < 3 else f"#{i + 1}"
        lines.append(f"{rank_display} — {member.mention} • {u[1]:,} msgs")
    lines.append("")
    if rank:
        lines.append(f"Your Rank: #{rank} • {ctx.author.mention}")
        lines.append(f"{user_msgs:,} msgs")
        lines.append(f"#{rank} • {total_members} members")
    else:
        lines.append("Your Rank: Unranked")
        lines.append("0 msgs")
        lines.append(f"#0 • {total_members} members")

    await ctx.send("\n".join(lines))

@bot.command(name='voice')
async def voice(ctx):
    top = c.execute("SELECT * FROM user_stats ORDER BY voice_seconds DESC LIMIT 10").fetchall()
    if not top:
        return await ctx.send("No data yet.")

    embed = discord.Embed(title="🔊 Voice Leaderboard")
    embed.description = format_leaderboard(top, True, ctx.guild)

    user_id = str(ctx.author.id)
    all_users = c.execute("SELECT user_id FROM user_stats ORDER BY voice_seconds DESC").fetchall()
    rank = None
    for i, u in enumerate(all_users, start=1):
        if u[0] == user_id:
            rank = i
            break

    user_data = c.execute("SELECT voice_seconds FROM user_stats WHERE user_id = ?", (user_id,)).fetchone()
    user_voice = user_data[0] if user_data else 0
    total_members = ctx.guild.member_count

    if rank:
        embed.add_field(
            name=f"Your Rank: #{rank} • {ctx.author.display_name}",
            value=f"{format_voice_time(user_voice)}\n# {rank} • {total_members} members",
            inline=False
        )
    else:
        embed.add_field(
            name="Your Rank: Unranked",
            value=f"0s\n# 0 • {total_members} members",
            inline=False
        )

    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_footer(text="⏳ Updates every 10 minutes")

    await ctx.send(embed=embed)

    # Plain-text output below embed
    lines = []
    lines.append("🔊 Voice Leaderboard\n")
    medals = ['🥇', '🥈', '🥉']
    for i, u in enumerate(top):
        member = ctx.guild.get_member(int(u[0]))
        if not member:
            continue
        rank_display = medals[i] if i < 3 else f"#{i + 1}"
        lines.append(f"{rank_display} — {member.mention} • {format_voice_time(u[2])}")
    lines.append("")
    if rank:
        lines.append(f"Your Rank: #{rank} • {ctx.author.mention}")
        lines.append(f"{format_voice_time(user_voice)}")
        lines.append(f"#{rank} • {total_members} members")
    else:
        lines.append("Your Rank: Unranked")
        lines.append("0s")
        lines.append(f"#0 • {total_members} members")

    await ctx.send("\n".join(lines))


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
        value = format_voice_time(u[2]) if is_voice else f"{u[1]:,} msgs"
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
