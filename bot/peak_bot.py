"""
PEAK Discord bot.

Reads every server's settings from the PEAK website (SITE_URL) using SYNC_KEY and
applies them live. Bot token / client id are taken from the website's admin panel,
so you only need SITE_URL and SYNC_KEY in .env.

Rate limits: discord.py already queues requests per Discord's rate-limit headers.
On top of that PEAK adds small delays for bulk actions (auto roles, lines, lockdown)
so the bot never floods the API.
"""
import asyncio
import hashlib
import io
import json
import os
import random
import re
import sqlite3
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageOps

load_dotenv()
# Render buffers Python output: without this the Logs tab stays empty and errors are invisible.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:  # noqa: BLE001
    pass
SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")
SYNC_KEY = os.environ.get("SYNC_KEY", "").strip()
if not SITE_URL or not SYNC_KEY:
    # Stay alive without touching Discord, so the host does not restart the bot in a loop.
    print("SITE_URL and SYNC_KEY are missing. Copy both from the website admin panel into the bot's Environment, then restart.")
    # Still answer Render's health check on PORT (Web Service), so Render does not kill it in a loop.
    if os.environ.get("PORT"):
        import http.server
        import socketserver

        class _H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b"PEAK bot: missing SITE_URL / SYNC_KEY")
            def do_HEAD(self):
                self.send_response(200); self.end_headers()

        socketserver.TCPServer(("0.0.0.0", int(os.environ["PORT"])), _H).serve_forever()
    while True:
        time.sleep(3600)
SYNC_EVERY = max(15, int(os.environ.get("SYNC_SECONDS", "30")))
FONT_PATH = os.environ.get("FONT_PATH", "")  # optional .ttf (use an Arabic-capable font for Arabic text)

SETTINGS: dict[str, dict] = {}
db = sqlite3.connect("peak.db")
db.executescript(
    """
CREATE TABLE IF NOT EXISTS xp(guild TEXT, user TEXT, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0, PRIMARY KEY(guild,user));
CREATE TABLE IF NOT EXISTS tickets(channel TEXT PRIMARY KEY, guild TEXT, owner TEXT, category TEXT, claimed_by TEXT, opened REAL);
CREATE TABLE IF NOT EXISTS warns(guild TEXT, user TEXT, mod TEXT, reason TEXT, at REAL);
CREATE TABLE IF NOT EXISTS app_cool(guild TEXT, form TEXT, user TEXT, at REAL, PRIMARY KEY(guild,form,user));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""
)
db.commit()

intents = discord.Intents.default()
intents.members = True          # privileged: enable "Server Members Intent" in the Developer Portal
intents.message_content = True  # privileged: enable "Message Content Intent"
intents.voice_states = True
client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
tree = app_commands.CommandTree(client)
http: aiohttp.ClientSession | None = None


# ------------------------------------------------------------------ helpers
def S(guild: discord.Guild | None) -> dict:
    return SETTINGS.get(str(guild.id), {}) if guild else {}


def g(d: dict, path: str, default=None):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def fill(text: str, member: discord.abc.User, guild: discord.Guild, level: int | None = None) -> str:
    return (
        (text or "")
        .replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{server}", guild.name)
        .replace("{memberCount}", str(guild.member_count))
        .replace("{level}", str(level or 0))
    )


def color(s: dict) -> int:
    try:
        return int(g(s, "general.embedColor", "#22d3ee").lstrip("#"), 16)
    except ValueError:
        return 0x22D3EE


def make_embed(e: dict, member=None, guild=None) -> discord.Embed:
    f = (lambda t: fill(t, member, guild)) if member and guild else (lambda t: t or "")
    em = discord.Embed(title=f(e.get("title")) or None, description=f(e.get("description")) or None)
    try:
        em.color = int((e.get("color") or "#22d3ee").lstrip("#"), 16)
    except ValueError:
        pass
    if str(e.get("imageUrl", "")).startswith("http"):
        em.set_image(url=e["imageUrl"])
    if str(e.get("thumbnailUrl", "")).startswith("http"):
        em.set_thumbnail(url=e["thumbnailUrl"])
    if e.get("footer"):
        em.set_footer(text=f(e["footer"]))
    if e.get("authorName"):
        em.set_author(name=f(e["authorName"]))
    return em


def channel(guild: discord.Guild, cid) -> discord.TextChannel | None:
    if not cid:
        return None
    ch = guild.get_channel(int(cid))
    return ch if isinstance(ch, (discord.TextChannel, discord.Thread)) else None


def whitelisted(member: discord.Member) -> bool:
    s = S(member.guild)
    if member.id == member.guild.owner_id or member.id == client.user.id:
        return True
    if str(member.id) in g(s, "protection.whitelistUsers", []):
        return True
    wl = set(g(s, "protection.whitelistRoles", []))
    return any(str(r.id) in wl for r in member.roles)


def is_mod(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    mods = set(g(S(member.guild), "general.modRoles", []))
    return any(str(r.id) in mods for r in member.roles)


async def log(guild: discord.Guild, key: str, title: str, desc: str, col=0x22D3EE, file: discord.File | None = None):
    s = S(guild)
    if key not in ("protectionLogs",) and not g(s, "logs.enabled"):
        return
    cid = g(s, f"logs.channels.{key}") or g(s, "logs.defaultChannelId")
    ch = channel(guild, cid)
    if not ch:
        return
    em = discord.Embed(title=title, description=desc[:4000], color=col, timestamp=datetime.now(timezone.utc))
    try:
        await ch.send(embed=em, file=file) if file else await ch.send(embed=em)
    except discord.HTTPException:
        pass


# ------------------------------------------------------------------ website sync
async def sync_loop():
    since = None
    while True:
        try:
            params = {"since": since} if since else {}
            async with http.get(f"{SITE_URL}/api/public/bot/sync", params=params, headers={"Authorization": f"Bearer {SYNC_KEY}"}) as r:
                if r.status == 200:
                    data = await r.json()
                    for row in data["guilds"]:
                        SETTINGS[row["guild_id"]] = row["settings"]
                    since = data["now"]
        except Exception as e:  # noqa: BLE001
            print("sync failed:", e)
        await asyncio.sleep(SYNC_EVERY)


async def stats_loop():
    await client.wait_until_ready()
    while True:
        try:
            open_t = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            body = {
                "servers": len(client.guilds),
                "users": sum(x.member_count or 0 for x in client.guilds),
                "active_tickets": open_t,
                "guild_ids": [str(x.id) for x in client.guilds],
            }
            async with http.post(f"{SITE_URL}/api/public/bot/sync", json=body, headers={"Authorization": f"Bearer {SYNC_KEY}"}) as r:
                if r.status != 200:
                    print(f"Website answered {r.status} to the online report. Check SITE_URL and SYNC_KEY.")
                else:
                    # The website keeps server info in memory: after it restarts, send everything again.
                    held = (await r.json(content_type=None) or {}).get("snapshots")
                    if isinstance(held, int) and held < len(_snap_sent):
                        _snap_sent.clear()
                        snapshot_soon()
        except Exception as e:  # noqa: BLE001
            print("stats failed:", e)
        await asyncio.sleep(120)


# ------------------------------------------------------------------ dashboard server info
# The dashboard shows each server's channels / roles. Instead of the website asking the Discord API
# on every page open (which got PEAK rate limited), the bot sends what it already has in memory from
# its Discord connection. That costs zero Discord API calls, and only changed servers are re-sent.
_snap_sent: dict[str, str] = {}  # guild id -> signature of the info the website already has
_snap_wake = asyncio.Event()


def snapshot_soon():
    """Ask for a push soon (channels / roles / servers changed). Several changes are sent together."""
    _snap_wake.set()


def _guild_snapshot(g: discord.Guild) -> dict:
    return {
        "id": str(g.id),
        "name": (g.name or "")[:200],
        "icon": g.icon.key if g.icon else None,
        "member_count": g.member_count or 0,
        "channels": [
            {
                "id": str(c.id),
                "name": (c.name or "")[:200],
                "type": int(getattr(c.type, "value", 0)),
                "parent_id": str(c.category_id) if c.category_id else None,
                "position": int(c.position or 0),
            }
            for c in g.channels
        ][:1500],
        "roles": [
            {"id": str(r.id), "name": (r.name or "")[:200], "color": int(r.color.value), "position": int(r.position), "managed": bool(r.managed)}
            for r in g.roles
        ][:1000],
    }


def _snapshot_sig(snap: dict) -> str:
    # Member count changes all the time, so it alone never triggers a re-send.
    return hashlib.sha256(json.dumps({k: v for k, v in snap.items() if k != "member_count"}, sort_keys=True).encode()).hexdigest()


async def push_snapshots() -> bool:
    """Sends changed server info to the website. Returns False when the website did not accept it."""
    guilds = [g for g in client.guilds if not g.unavailable]
    all_ids = [str(g.id) for g in client.guilds]
    id_set = set(all_ids)
    changed = []
    for g in guilds:
        snap = _guild_snapshot(g)
        sig = _snapshot_sig(snap)
        if _snap_sent.get(snap["id"]) != sig:
            changed.append((snap, sig))
    removed = [gid for gid in _snap_sent if gid not in id_set]
    if not changed and not removed:
        return True
    for i in range(0, max(len(changed), 1), 10):
        chunk = changed[i : i + 10]
        body = {"snapshots": [snap for snap, _ in chunk], "removed": removed if i == 0 else [], "all_ids": all_ids}
        async with http.post(
            f"{SITE_URL}/api/public/bot/sync",
            json=body,
            headers={"Authorization": f"Bearer {SYNC_KEY}"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as r:
            if r.status != 200:
                print(f"Website answered {r.status} to the server info push (update the website to the latest version).")
                return False
        for snap, sig in chunk:
            _snap_sent[snap["id"]] = sig
        await asyncio.sleep(0.5)
    for gid in removed:
        _snap_sent.pop(gid, None)
    return True


async def snapshot_loop():
    await client.wait_until_ready()
    while True:
        try:
            ok = await push_snapshots()
        except Exception as e:  # noqa: BLE001
            print("server info push failed:", e)
            ok = False
        try:
            # Re-check every minute (local only, no Discord calls); sooner when something changed.
            await asyncio.wait_for(_snap_wake.wait(), timeout=60 if ok else 600)
        except asyncio.TimeoutError:
            pass
        _snap_wake.clear()
        await asyncio.sleep(5)  # gathers a burst of channel / role edits into one push


# ------------------------------------------------------------------ welcome image
async def fetch_bytes(url: str) -> bytes | None:
    try:
        async with http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200 and int(r.headers.get("content-length", 0) or 0) < 8_000_000:
                return await r.read()
    except Exception:  # noqa: BLE001
        return None
    return None


def font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH or "DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


async def welcome_card(member: discord.Member, cfg: dict) -> discord.File:
    W, H = 1024, 450
    bg_bytes = await fetch_bytes(cfg.get("background", "")) if cfg.get("background") else None
    if bg_bytes:
        bg = ImageOps.fit(Image.open(io.BytesIO(bg_bytes)).convert("RGBA"), (W, H))
    else:
        bg = Image.new("RGBA", (W, H), (14, 22, 38, 255))
    overlay = Image.new("RGBA", (W, H), (10, 14, 24, int(255 * cfg.get("overlay", 40) / 100)))
    bg = Image.alpha_composite(bg, overlay)
    av_bytes = await fetch_bytes(member.display_avatar.replace(size=256, format="png").url)
    accent = cfg.get("accentColor", "#22d3ee")
    if av_bytes:
        av = Image.open(io.BytesIO(av_bytes)).convert("RGBA").resize((200, 200))
        mask = Image.new("L", (200, 200), 0)
        d = ImageDraw.Draw(mask)
        (d.ellipse if cfg.get("avatarShape") != "square" else d.rounded_rectangle)((0, 0, 200, 200), **({} if cfg.get("avatarShape") != "square" else {"radius": 30}), fill=255)
        ring = Image.new("RGBA", (216, 216), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        (rd.ellipse if cfg.get("avatarShape") != "square" else rd.rounded_rectangle)((0, 0, 216, 216), **({} if cfg.get("avatarShape") != "square" else {"radius": 36}), fill=accent)
        bg.paste(ring, ((W - 216) // 2, 30), ring)
        bg.paste(av, ((W - 200) // 2, 38), mask)
    draw = ImageDraw.Draw(bg)
    txt = cfg.get("textColor", "#ffffff")
    for text, y, size, col in (
        (fill(cfg.get("title", "WELCOME"), member, member.guild), 270, 60, txt),
        (fill(cfg.get("subtitle", "{username}"), member, member.guild).replace(member.mention, member.name), 345, 38, accent),
        (fill(cfg.get("footer", ""), member, member.guild).replace(member.mention, member.name), 400, 26, txt),
    ):
        if text:
            draw.text((W // 2, y), text, font=font(size), fill=col, anchor="mm")
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return discord.File(buf, filename="welcome.png")


# ------------------------------------------------------------------ protection state
join_times: dict[int, deque] = defaultdict(deque)
msg_times: dict[tuple, deque] = defaultdict(deque)
nuke_counts: dict[tuple, deque] = defaultdict(deque)
line_last: dict[int, float] = {}
xp_last: dict[tuple, float] = {}


def bump(store, key, window) -> int:
    now = time.monotonic()
    dq = store[key]
    dq.append(now)
    while dq and now - dq[0] > window:
        dq.popleft()
    return len(dq)


async def punish(member: discord.Member, action: str, reason: str, minutes: int = 10):
    try:
        if action == "timeout":
            await member.timeout(timedelta(minutes=minutes), reason=reason)
        elif action == "kick":
            await member.kick(reason=reason)
        elif action == "ban":
            await member.ban(reason=reason, delete_message_days=0)
        elif action == "removeRoles":
            roles = [r for r in member.roles if r.is_assignable()]
            await member.remove_roles(*roles, reason=reason)
    except discord.HTTPException:
        pass
    await log(member.guild, "protectionLogs", "🛡️ Protection", f"{member.mention} → **{action}**\n{reason}", 0xEF4444)


async def check_nuke(guild: discord.Guild, kind: str, audit_action):
    s = S(guild)
    if not g(s, "protection.antiNuke.enabled"):
        return
    try:
        async for entry in guild.audit_logs(limit=1, action=audit_action):
            actor = entry.user
            if not isinstance(actor, discord.Member) or whitelisted(actor):
                return
            limit = g(s, f"protection.antiNuke.{kind}Limit", 3)
            n = bump(nuke_counts, (guild.id, actor.id, kind), g(s, "protection.antiNuke.perSeconds", 60))
            if n >= limit:
                await punish(actor, g(s, "protection.antiNuke.action", "removeRoles"), f"Anti-nuke: {n} {kind} actions")
    except discord.Forbidden:
        pass


# ------------------------------------------------------------------ events: members
@client.event
async def on_member_join(member: discord.Member):
    guild, s = member.guild, S(member.guild)
    p = g(s, "protection", {})
    await log(guild, "memberJoin", "📥 Member joined", f"{member.mention} ({member.id})\nCreated <t:{int(member.created_at.timestamp())}:R>", 0x22C55E)

    if member.bot:
        if g(p, "antiBots.enabled"):
            try:
                async for e in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                    if isinstance(e.user, discord.Member) and not whitelisted(e.user):
                        await punish(member, "kick", "Anti-bot: added by untrusted member")
                        return
            except discord.Forbidden:
                pass
        for rid in g(s, "welcome.botRoles", []):
            role = guild.get_role(int(rid))
            if role:
                await member.add_roles(role, reason="PEAK bot auto role")
                await asyncio.sleep(1)
        return

    if g(p, "antiAlt.enabled"):
        age = (datetime.now(timezone.utc) - member.created_at).days
        if age < g(p, "antiAlt.minAgeDays", 7):
            await punish(member, g(p, "antiAlt.action", "kick"), f"Anti-alt: account is {age} days old")
            return

    if g(p, "antiRaid.enabled"):
        n = bump(join_times, guild.id, g(p, "antiRaid.perSeconds", 10))
        if n >= g(p, "antiRaid.joinLimit", 10):
            await log(guild, "protectionLogs", "🚨 Raid detected", f"{n} joins — raising verification level", 0xEF4444)
            try:
                await guild.edit(verification_level=discord.VerificationLevel.highest, reason="PEAK anti-raid")
            except discord.HTTPException:
                pass

    for rid in g(s, "welcome.autoRoles", []):
        role = guild.get_role(int(rid))
        if role and role < guild.me.top_role:
            try:
                await member.add_roles(role, reason="PEAK auto role")
            except discord.HTTPException:
                pass
            await asyncio.sleep(1)  # gentle on rate limits

    w = g(s, "welcome", {})
    if w.get("enabled"):
        ch = channel(guild, w.get("channelId"))
        if ch:
            kwargs = {"content": fill(w.get("message", ""), member, guild) or None}
            if w.get("useEmbed"):
                kwargs["embed"] = make_embed(w.get("embed", {}), member, guild)
            if w.get("useImage"):
                kwargs["file"] = await welcome_card(member, w.get("image", {}))
                if "embed" in kwargs:
                    kwargs["embed"].set_image(url="attachment://welcome.png")
            try:
                await ch.send(**kwargs)
            except discord.HTTPException:
                pass
    if g(w, "dm.enabled"):
        try:
            await member.send(fill(g(w, "dm.message", ""), member, guild))
        except discord.HTTPException:
            pass


@client.event
async def on_member_remove(member: discord.Member):
    guild, s = member.guild, S(member.guild)
    await log(guild, "memberLeave", "📤 Member left", f"{member} ({member.id})", 0xF97316)
    if g(s, "leave.enabled"):
        ch = channel(guild, g(s, "leave.channelId"))
        if ch:
            await ch.send(fill(g(s, "leave.message", ""), member, guild))
    try:
        async for e in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if e.target and e.target.id == member.id and (datetime.now(timezone.utc) - e.created_at).seconds < 10:
                await log(guild, "kick", "👢 Kick", f"{member} by {e.user.mention}\nReason: {e.reason}", 0xF97316)
    except discord.Forbidden:
        pass


@client.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.nick != after.nick:
        await log(after.guild, "memberNick", "✏️ Nickname", f"{after.mention}: `{before.nick}` → `{after.nick}`")
    if before.roles != after.roles:
        added = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        await log(after.guild, "memberRoles", "🎭 Roles updated", f"{after.mention}\n➕ {' '.join(added) or '-'}\n➖ {' '.join(removed) or '-'}")
    if before.timed_out_until != after.timed_out_until and after.timed_out_until:
        await log(after.guild, "timeout", "🔇 Timeout", f"{after.mention} until <t:{int(after.timed_out_until.timestamp())}:f>", 0xF59E0B)
    if before.guild_avatar != after.guild_avatar:
        await log(after.guild, "memberAvatar", "🖼️ Avatar", after.mention)


@client.event
async def on_member_ban(guild, user):
    await log(guild, "ban", "🔨 Ban", f"{user} ({user.id})", 0xEF4444)
    await check_nuke(guild, "ban", discord.AuditLogAction.ban)


@client.event
async def on_member_unban(guild, user):
    await log(guild, "unban", "🔓 Unban", f"{user} ({user.id})", 0x22C55E)


# ------------------------------------------------------------------ events: server
@client.event
async def on_guild_join(guild):
    snapshot_soon()  # the dashboard shows "Manage" for the new server within seconds


@client.event
async def on_guild_remove(guild):
    snapshot_soon()


@client.event
async def on_guild_channel_create(ch):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    await log(ch.guild, "channelCreate", "➕ Channel created", f"{ch.mention if hasattr(ch, 'mention') else ch.name}")


@client.event
async def on_guild_channel_delete(ch):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    await log(ch.guild, "channelDelete", "🗑️ Channel deleted", f"#{ch.name}", 0xEF4444)
    await check_nuke(ch.guild, "channelDelete", discord.AuditLogAction.channel_delete)
    db.execute("DELETE FROM tickets WHERE channel=?", (str(ch.id),))
    db.commit()


@client.event
async def on_guild_channel_update(b, a):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    if b.name != a.name:
        await log(a.guild, "channelUpdate", "🔧 Channel updated", f"#{b.name} → #{a.name}")


@client.event
async def on_guild_role_create(r):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    await log(r.guild, "roleCreate", "➕ Role created", r.mention)


@client.event
async def on_guild_role_delete(r):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    await log(r.guild, "roleDelete", "🗑️ Role deleted", r.name, 0xEF4444)
    await check_nuke(r.guild, "roleDelete", discord.AuditLogAction.role_delete)


@client.event
async def on_guild_role_update(b, a):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    if b.name != a.name or b.permissions != a.permissions or b.color != a.color:
        await log(a.guild, "roleUpdate", "🔧 Role updated", f"{a.mention} (`{b.name}` → `{a.name}`)")


@client.event
async def on_guild_update(b, a):
    snapshot_soon()  # refresh the dashboard's server info (no Discord API call)
    if b.name != a.name or b.icon != a.icon:
        await log(a, "serverUpdate", "🏠 Server updated", f"`{b.name}` → `{a.name}`")


@client.event
async def on_guild_emojis_update(guild, before, after):
    await log(guild, "emojiUpdate", "😀 Emojis updated", f"{len(before)} → {len(after)}")


@client.event
async def on_invite_create(inv):
    await log(inv.guild, "inviteCreate", "🔗 Invite created", f"{inv.url} by {inv.inviter}")


@client.event
async def on_thread_create(t):
    await log(t.guild, "threadCreate", "🧵 Thread created", t.mention)


@client.event
async def on_webhooks_update(ch):
    if not g(S(ch.guild), "protection.antiWebhook.enabled"):
        return
    try:
        async for e in ch.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
            if isinstance(e.user, discord.Member) and not whitelisted(e.user):
                for wh in await ch.webhooks():
                    if wh.user and wh.user.id == e.user.id:
                        await wh.delete(reason="PEAK anti-webhook")
                await log(ch.guild, "protectionLogs", "🛡️ Webhook removed", f"Created by {e.user.mention}", 0xEF4444)
    except discord.Forbidden:
        pass


# ------------------------------------------------------------------ events: messages
@client.event
async def on_message_delete(m: discord.Message):
    if m.guild and not m.author.bot and str(m.channel.id) not in g(S(m.guild), "logs.ignoredChannels", []):
        await log(m.guild, "messageDelete", "🗑️ Message deleted", f"{m.author.mention} in {m.channel.mention}\n{m.content[:1800]}", 0xEF4444)


@client.event
async def on_bulk_message_delete(msgs):
    if msgs and msgs[0].guild:
        await log(msgs[0].guild, "messageBulkDelete", "🧹 Bulk delete", f"{len(msgs)} messages in {msgs[0].channel.mention}", 0xEF4444)


@client.event
async def on_message_edit(b: discord.Message, a: discord.Message):
    if a.guild and not a.author.bot and b.content != a.content:
        await log(a.guild, "messageEdit", "✏️ Message edited", f"{a.author.mention} in {a.channel.mention} [jump]({a.jump_url})\n**Before:** {b.content[:900]}\n**After:** {a.content[:900]}")


INVITE_RE = re.compile(r"(discord\.gg|discord(app)?\.com/invite)/\S+", re.I)
LINK_RE = re.compile(r"https?://\S+", re.I)


@client.event
async def on_message(m: discord.Message):
    if not m.guild or m.author.bot or not isinstance(m.author, discord.Member):
        return
    s = S(m.guild)
    p = g(s, "protection", {})
    trusted = whitelisted(m.author) or m.author.guild_permissions.administrator

    if not trusted:
        if g(p, "antiLink.enabled") and str(m.channel.id) not in g(p, "antiLink.allowedChannels", []):
            if (g(p, "antiLink.blockInvites") and INVITE_RE.search(m.content)) or (g(p, "antiLink.blockAllLinks") and LINK_RE.search(m.content)):
                await m.delete()
                await log(m.guild, "protectionLogs", "🔗 Link blocked", f"{m.author.mention} in {m.channel.mention}", 0xEF4444)
                return
        if g(p, "badWords.enabled") and any(w.lower() in m.content.lower() for w in g(p, "badWords.words", [])):
            await m.delete()
            return
        if g(p, "antiMassMention.enabled") and len(m.mentions) >= g(p, "antiMassMention.limit", 5):
            await m.delete()
            await punish(m.author, g(p, "antiMassMention.action", "timeout"), "Mass mention")
            return
        if g(p, "antiSpam.enabled"):
            n = bump(msg_times, (m.guild.id, m.author.id), g(p, "antiSpam.perSeconds", 5))
            if n >= g(p, "antiSpam.maxMessages", 5):
                msg_times[(m.guild.id, m.author.id)].clear()
                await punish(m.author, g(p, "antiSpam.action", "timeout"), "Spam", g(p, "antiSpam.timeoutMinutes", 10))
                return

    # auto line
    al = g(s, "autoLine", {})
    if al.get("enabled"):
        for line in al.get("lines", []):
            if line.get("channelId") == str(m.channel.id) and line.get("imageUrl"):
                cd = max(2, al.get("cooldownSeconds", 3))
                if time.monotonic() - line_last.get(m.channel.id, 0) >= cd:
                    line_last[m.channel.id] = time.monotonic()
                    await m.channel.send(line["imageUrl"])
                break

    # XP
    lv = g(s, "levels", {})
    if lv.get("enabled") and str(m.channel.id) not in lv.get("noXpChannels", []) and not any(str(r.id) in lv.get("noXpRoles", []) for r in m.author.roles):
        key = (m.guild.id, m.author.id)
        if time.monotonic() - xp_last.get(key, 0) >= lv.get("cooldownSeconds", 60):
            xp_last[key] = time.monotonic()
            await add_xp(m.author, random.randint(lv.get("textXpMin", 15), max(lv.get("textXpMin", 15), lv.get("textXpMax", 25))), m.channel)

    await handle_command(m, s)


# ------------------------------------------------------------------ levels
def need(level: int) -> int:  # same curve as ProBot / MEE6
    return 5 * level * level + 50 * level + 100


async def add_xp(member: discord.Member, amount: int, where=None):
    gid, uid = str(member.guild.id), str(member.id)
    row = db.execute("SELECT xp, level FROM xp WHERE guild=? AND user=?", (gid, uid)).fetchone() or (0, 0)
    xp, level = row[0] + amount, row[1]
    leveled = False
    while xp >= need(level):
        xp -= need(level)
        level += 1
        leveled = True
    db.execute("INSERT OR REPLACE INTO xp VALUES (?,?,?,?)", (gid, uid, xp, level))
    db.commit()
    if not leveled:
        return
    lv = g(S(member.guild), "levels", {})
    if lv.get("announce"):
        ch = channel(member.guild, lv.get("levelUpChannelId")) or where
        if ch:
            await ch.send(fill(lv.get("levelUpMessage", ""), member, member.guild, level))
    rewards = sorted(lv.get("rewards", []), key=lambda r: r["level"])
    for r in rewards:
        role = member.guild.get_role(int(r["roleId"])) if r.get("roleId") else None
        if not role:
            continue
        if r["level"] <= level and role not in member.roles:
            await member.add_roles(role, reason=f"Level {level} reward")
            await asyncio.sleep(1)
        elif not lv.get("stackRewards", True) and r["level"] < level and role in member.roles:
            higher = [x for x in rewards if r["level"] < x["level"] <= level]
            if higher:
                await member.remove_roles(role, reason="Level reward replaced")


async def voice_loop():
    await client.wait_until_ready()
    while True:
        await asyncio.sleep(60)
        for guild in client.guilds:
            lv = g(S(guild), "levels", {})
            if not (lv.get("enabled") and lv.get("voiceEnabled")):
                continue
            for vc in guild.voice_channels:
                humans = [mm for mm in vc.members if not mm.bot]
                if len(humans) < 2:
                    continue
                for mm in humans:
                    if not (mm.voice.self_mute or mm.voice.self_deaf or mm.voice.afk):
                        await add_xp(mm, lv.get("voiceXpPerMinute", 10))


@client.event
async def on_voice_state_update(member, before, after):
    if before.channel == after.channel:
        if before.self_mute != after.self_mute or before.mute != after.mute:
            await log(member.guild, "voiceMute", "🎙️ Voice mute", f"{member.mention} muted={after.self_mute or after.mute}")
        return
    if not before.channel:
        await log(member.guild, "voiceJoin", "🔊 Voice join", f"{member.mention} → {after.channel.mention}", 0x22C55E)
    elif not after.channel:
        await log(member.guild, "voiceLeave", "🔈 Voice leave", f"{member.mention} ← {before.channel.mention}", 0xF97316)
    else:
        await log(member.guild, "voiceMove", "🔀 Voice move", f"{member.mention}: {before.channel.mention} → {after.channel.mention}")


# ------------------------------------------------------------------ prefix commands
def parse_member(guild: discord.Guild, token: str | None):
    if not token:
        return None
    mid = re.sub(r"\D", "", token)
    return guild.get_member(int(mid)) if mid else None


async def handle_command(m: discord.Message, s: dict):
    prefix = g(s, "general.prefix", "!") or "!"
    if not m.content.startswith(prefix):
        return
    parts = m.content[len(prefix):].split()
    if not parts:
        return
    word = parts[0].lower()
    cmds = g(s, "general.commands", {})
    name = next((c for c, v in cmds.items() if word == c or word in [a.lower() for a in v.get("aliases", [])]), word)
    if cmds.get(name, {}).get("enabled") is False:
        return
    args = parts[1:]
    author: discord.Member = m.author
    guild = m.guild
    em_col = color(s)

    async def reply(text: str):
        await m.channel.send(embed=discord.Embed(description=text, color=em_col))

    mod_cmds = {"ban", "unban", "kick", "timeout", "untimeout", "warn", "clear", "lock", "unlock", "slowmode", "say", "embed", "role", "nick"}
    if name in mod_cmds and not is_mod(author):
        return
    target = parse_member(guild, args[0] if args else None)
    reason = " ".join(args[1:]) or "No reason"
    try:
        if name == "ban" and target:
            await target.ban(reason=f"{author}: {reason}", delete_message_days=0)
            await reply(f"🔨 {target} banned")
            await log(guild, "ban", "🔨 Ban (command)", f"{target} by {author.mention}\n{reason}", 0xEF4444)
        elif name == "unban" and args:
            await guild.unban(discord.Object(int(re.sub(r"\D", "", args[0]))))
            await reply("🔓 Unbanned")
        elif name == "kick" and target:
            await target.kick(reason=f"{author}: {reason}")
            await reply(f"👢 {target} kicked")
            await log(guild, "kick", "👢 Kick (command)", f"{target} by {author.mention}\n{reason}", 0xF97316)
        elif name == "timeout" and target:
            mins = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
            await target.timeout(timedelta(minutes=mins), reason=f"{author}: {' '.join(args[2:])}")
            await reply(f"🔇 {target.mention} timed out {mins}m")
        elif name == "untimeout" and target:
            await target.timeout(None)
            await reply(f"🔊 {target.mention} un-timed out")
        elif name == "warn" and target:
            db.execute("INSERT INTO warns VALUES (?,?,?,?,?)", (str(guild.id), str(target.id), str(author.id), reason, time.time()))
            db.commit()
            await reply(f"⚠️ {target.mention} warned: {reason}")
            await log(guild, "warn", "⚠️ Warn", f"{target.mention} by {author.mention}\n{reason}", 0xF59E0B)
        elif name == "warnings":
            t = target or author
            rows = db.execute("SELECT reason, at FROM warns WHERE guild=? AND user=? ORDER BY at DESC LIMIT 10", (str(guild.id), str(t.id))).fetchall()
            await reply("\n".join(f"• {r[0]} (<t:{int(r[1])}:R>)" for r in rows) or "No warnings")
        elif name == "clear":
            n = min(100, int(args[0])) if args and args[0].isdigit() else 10
            await m.channel.purge(limit=n + 1)
        elif name in ("lock", "unlock"):
            await m.channel.set_permissions(guild.default_role, send_messages=(name == "unlock"))
            await reply("🔒 Locked" if name == "lock" else "🔓 Unlocked")
        elif name == "slowmode":
            await m.channel.edit(slowmode_delay=min(21600, int(args[0]) if args and args[0].isdigit() else 0))
            await reply("🐢 Slowmode updated")
        elif name == "say" and args:
            await m.channel.send(" ".join(args), allowed_mentions=discord.AllowedMentions.none())
        elif name == "embed" and args:
            await m.channel.send(embed=discord.Embed(description=" ".join(args), color=em_col))
        elif name == "role" and target and len(args) > 1:
            role = guild.get_role(int(re.sub(r"\D", "", args[1]) or 0))
            if role and role < author.top_role:
                await (target.remove_roles if role in target.roles else target.add_roles)(role)
                await reply("✅ Role toggled")
        elif name == "nick" and target:
            await target.edit(nick=" ".join(args[1:]) or None)
            await reply("✅ Nickname updated")
        elif name == "rank":
            await m.channel.send(embed=rank_embed(target or author, em_col))
        elif name == "top":
            await m.channel.send(embed=top_embed(guild, em_col))
        elif name == "avatar":
            t = target or author
            await m.channel.send(embed=discord.Embed(title=str(t), color=em_col).set_image(url=t.display_avatar.url))
        elif name == "serverinfo":
            e = discord.Embed(title=guild.name, color=em_col)
            e.add_field(name="Members", value=guild.member_count).add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:R>")
            e.add_field(name="Owner", value=f"<@{guild.owner_id}>").add_field(name="Boosts", value=guild.premium_subscription_count)
            if guild.icon:
                e.set_thumbnail(url=guild.icon.url)
            await m.channel.send(embed=e)
        elif name == "userinfo":
            t = target or author
            e = discord.Embed(title=str(t), color=em_col).set_thumbnail(url=t.display_avatar.url)
            e.add_field(name="Joined", value=f"<t:{int(t.joined_at.timestamp())}:R>").add_field(name="Created", value=f"<t:{int(t.created_at.timestamp())}:R>")
            await m.channel.send(embed=e)
        else:
            return
        if g(s, "general.deleteCommandMessage") and name != "clear":
            await m.delete()
    except discord.Forbidden:
        await reply("❌ I don't have permission for that.")
    except discord.HTTPException as e:
        await reply(f"❌ {e.text}")


def rank_embed(member: discord.Member, col: int) -> discord.Embed:
    gid = str(member.guild.id)
    row = db.execute("SELECT xp, level FROM xp WHERE guild=? AND user=?", (gid, str(member.id))).fetchone() or (0, 0)
    pos = db.execute("SELECT COUNT(*) FROM xp WHERE guild=? AND (level>? OR (level=? AND xp>?))", (gid, row[1], row[1], row[0])).fetchone()[0] + 1
    bar_n = int(12 * row[0] / need(row[1]))
    e = discord.Embed(title=f"{member.display_name} — Level {row[1]}", color=col)
    e.description = f"Rank **#{pos}**\n`{'█' * bar_n}{'░' * (12 - bar_n)}` {row[0]}/{need(row[1])} XP"
    return e.set_thumbnail(url=member.display_avatar.url)


def top_embed(guild: discord.Guild, col: int) -> discord.Embed:
    rows = db.execute("SELECT user, level, xp FROM xp WHERE guild=? ORDER BY level DESC, xp DESC LIMIT 10", (str(guild.id),)).fetchall()
    return discord.Embed(title="🏆 Leaderboard", color=col, description="\n".join(f"**{i + 1}.** <@{u}> — Level {lv}" for i, (u, lv, _) in enumerate(rows)) or "No data yet")


@tree.command(name="rank", description="Show your level")
async def slash_rank(inter: discord.Interaction, member: discord.Member | None = None):
    await inter.response.send_message(embed=rank_embed(member or inter.user, color(S(inter.guild))))


@tree.command(name="top", description="Server leaderboard")
async def slash_top(inter: discord.Interaction):
    await inter.response.send_message(embed=top_embed(inter.guild, color(S(inter.guild))))


# ------------------------------------------------------------------ tickets & applications (components)
class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, custom_id="peak:ticket:claim", emoji="🙋")
    async def claim(self, inter: discord.Interaction, _):
        if not is_support(inter.user):
            return await inter.response.send_message("Support only.", ephemeral=True)
        db.execute("UPDATE tickets SET claimed_by=? WHERE channel=?", (str(inter.user.id), str(inter.channel.id)))
        db.commit()
        await inter.response.send_message(f"🙋 Claimed by {inter.user.mention}")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="peak:ticket:close", emoji="🔒")
    async def close(self, inter: discord.Interaction, _):
        row = db.execute("SELECT owner, category FROM tickets WHERE channel=?", (str(inter.channel.id),)).fetchone()
        if not row:
            return await inter.response.send_message("Not a ticket.", ephemeral=True)
        if not (is_support(inter.user) or str(inter.user.id) == row[0]):
            return await inter.response.send_message("No permission.", ephemeral=True)
        await inter.response.send_message("🔒 Closing in 5 seconds…")
        s = S(inter.guild)
        if g(s, "tickets.transcripts"):
            lines = [f"[{x.created_at:%Y-%m-%d %H:%M}] {x.author}: {x.content}" + "".join(f" [{a.url}]" for a in x.attachments) async for x in inter.channel.history(limit=1000, oldest_first=True)]
            f = discord.File(io.BytesIO("\n".join(lines).encode()), filename=f"transcript-{inter.channel.name}.txt")
            tch = channel(inter.guild, g(s, "tickets.transcriptChannelId"))
            desc = f"Ticket `{inter.channel.name}` · owner <@{row[0]}> · closed by {inter.user.mention}"
            if tch:
                await tch.send(embed=discord.Embed(title="📁 Transcript", description=desc, color=color(s)), file=f)
            else:
                await log(inter.guild, "ticketLogs", "📁 Transcript", desc, file=f)
        db.execute("DELETE FROM tickets WHERE channel=?", (str(inter.channel.id),))
        db.commit()
        await asyncio.sleep(5)
        await inter.channel.delete(reason="Ticket closed")


def is_support(member: discord.Member) -> bool:
    if is_mod(member):
        return True
    t = g(S(member.guild), "tickets", {})
    roles = set(t.get("supportRoles", []))
    for c in t.get("categories", []):
        roles |= set(c.get("supportRoles", []))
    return any(str(r.id) in roles for r in member.roles)


async def open_ticket(inter: discord.Interaction, cat_id: str):
    guild, s = inter.guild, S(inter.guild)
    t = g(s, "tickets", {})
    if not t.get("enabled"):
        return await inter.response.send_message("Tickets are disabled.", ephemeral=True)
    open_n = db.execute("SELECT COUNT(*) FROM tickets WHERE guild=? AND owner=?", (str(guild.id), str(inter.user.id))).fetchone()[0]
    if open_n >= t.get("maxOpenPerUser", 1):
        return await inter.response.send_message("You already have an open ticket.", ephemeral=True)
    cat = next((c for c in t.get("categories", []) if c["id"] == cat_id), {"label": "ticket", "supportRoles": [], "categoryChannelId": ""})
    parent = guild.get_channel(int(cat.get("categoryChannelId") or t.get("categoryChannelId") or 0)) if (cat.get("categoryChannelId") or t.get("categoryChannelId")) else None
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False), inter.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
    for rid in set(t.get("supportRoles", [])) | set(cat.get("supportRoles", [])):
        role = guild.get_role(int(rid))
        if role:
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    await inter.response.defer(ephemeral=True)
    ch = await guild.create_text_channel(f"ticket-{inter.user.name}"[:90], category=parent if isinstance(parent, discord.CategoryChannel) else None, overwrites=ow, reason="PEAK ticket")
    db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?)", (str(ch.id), str(guild.id), str(inter.user.id), cat_id, None, time.time()))
    db.commit()
    view = TicketControls()
    if not t.get("claimEnabled", True):
        view.remove_item(view.children[0])
    await ch.send(content=inter.user.mention, embed=discord.Embed(title=f"{cat.get('emoji', '')} {cat.get('label')}", description=fill(t.get("openMessage", ""), inter.user, guild), color=color(s)), view=view)
    await inter.followup.send(f"✅ Ticket opened: {ch.mention}", ephemeral=True)
    await log(guild, "ticketLogs", "🎫 Ticket opened", f"{inter.user.mention} → {ch.mention} ({cat.get('label')})")


class ApplyModal(discord.ui.Modal):
    def __init__(self, form: dict):
        super().__init__(title=form["name"][:45] or "Application", custom_id=f"peak:appmodal:{form['id']}")
        self.form = form
        for q in form.get("questions", [])[:5]:
            self.add_item(discord.ui.TextInput(label=(q or "Question")[:45], style=discord.TextStyle.paragraph, max_length=1000))

    async def on_submit(self, inter: discord.Interaction):
        f = self.form
        db.execute("INSERT OR REPLACE INTO app_cool VALUES (?,?,?,?)", (str(inter.guild.id), f["id"], str(inter.user.id), time.time()))
        db.commit()
        em = discord.Embed(title=f"📝 {f['name']}", color=color(S(inter.guild)), description=f"From {inter.user.mention} ({inter.user.id})")
        for item in self.children:
            em.add_field(name=item.label, value=item.value[:1024] or "-", inline=False)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Accept", style=discord.ButtonStyle.success, custom_id=f"peak:app:accept:{f['id']}:{inter.user.id}"))
        view.add_item(discord.ui.Button(label="Reject", style=discord.ButtonStyle.danger, custom_id=f"peak:app:reject:{f['id']}:{inter.user.id}"))
        ch = channel(inter.guild, f.get("reviewChannelId"))
        if ch:
            await ch.send(embed=em, view=view)
        await inter.response.send_message("✅ Your application was submitted.", ephemeral=True)
        await log(inter.guild, "applicationLogs", "📝 Application", f"{inter.user.mention} applied for **{f['name']}**")


@client.event
async def on_interaction(inter: discord.Interaction):
    if inter.type != discord.InteractionType.component or not inter.guild:
        return
    cid = (inter.data or {}).get("custom_id", "")
    s = S(inter.guild)
    if cid == "peak:ticket:open":
        await open_ticket(inter, (inter.data.get("values") or [""])[0])
    elif cid.startswith("peak:apply:"):
        a = g(s, "applications", {})
        form = next((f for f in a.get("forms", []) if f["id"] == cid.split(":")[2]), None)
        if not a.get("enabled") or not form or not form.get("open"):
            return await inter.response.send_message("Applications are closed.", ephemeral=True)
        last = db.execute("SELECT at FROM app_cool WHERE guild=? AND form=? AND user=?", (str(inter.guild.id), form["id"], str(inter.user.id))).fetchone()
        if last and time.time() - last[0] < form.get("cooldownHours", 24) * 3600:
            return await inter.response.send_message(f"You can apply again <t:{int(last[0] + form['cooldownHours'] * 3600)}:R>.", ephemeral=True)
        await inter.response.send_modal(ApplyModal(form))
    elif cid.startswith("peak:app:"):
        _, _, verdict, form_id, uid = cid.split(":")
        if not is_mod(inter.user):
            return await inter.response.send_message("Staff only.", ephemeral=True)
        form = next((f for f in g(s, "applications.forms", []) if f["id"] == form_id), {})
        member = inter.guild.get_member(int(uid))
        if verdict == "accept" and member:
            for rid in form.get("acceptRoles", []):
                role = inter.guild.get_role(int(rid))
                if role:
                    await member.add_roles(role, reason="Application accepted")
                    await asyncio.sleep(1)
        if member:
            try:
                await member.send(f"Your application **{form.get('name', '')}** in **{inter.guild.name}** was **{'accepted ✅' if verdict == 'accept' else 'rejected ❌'}**.")
            except discord.HTTPException:
                pass
        await inter.response.edit_message(content=f"{'✅ Accepted' if verdict == 'accept' else '❌ Rejected'} by {inter.user.mention}", view=None)


# ------------------------------------------------------------------ startup
_ready_once = False


def _commands_signature() -> str:
    import hashlib
    import json
    try:
        cmds = sorted((c.to_dict(tree) for c in tree.get_commands()), key=lambda c: c.get("name", ""))
    except TypeError:  # older discord.py
        cmds = sorted((c.to_dict() for c in tree.get_commands()), key=lambda c: c.get("name", ""))
    return hashlib.sha256(json.dumps(cmds, sort_keys=True, default=str).encode()).hexdigest()


@client.event
async def on_ready():
    # on_ready fires again after every reconnect: do the one-time work only once per run.
    global _ready_once
    if _ready_once:
        return
    _ready_once = True
    client.add_view(TicketControls())  # persistent ticket buttons survive restarts
    asyncio.create_task(stats_loop())  # tells the website the bot is online (every 2 minutes)
    asyncio.create_task(snapshot_loop())  # sends channels / roles to the dashboard (no Discord API calls)
    asyncio.create_task(voice_loop())
    # Slash commands are only re-registered when they actually changed (Discord limits this strictly).
    sig = _commands_signature()
    row = db.execute("SELECT v FROM meta WHERE k='cmd_sig'").fetchone()
    if not row or row[0] != sig:
        try:
            await tree.sync()
            db.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('cmd_sig', ?)", (sig,))
            db.commit()
        except discord.HTTPException as e:
            print("slash sync failed:", e)
    print(f"PEAK online as {client.user} in {len(client.guilds)} servers")
    print(f"Reporting to {SITE_URL} (admin panel turns green within a minute)")


async def fetch_site_config() -> dict:
    """Reads the token and settings from the website, waiting politely when it is not reachable."""
    delay = 30
    while True:
        try:
            async with http.get(f"{SITE_URL}/api/public/bot/sync", headers={"Authorization": f"Bearer {SYNC_KEY}"}) as r:
                if r.status == 200:
                    return await r.json()
                print(f"Website answered {r.status}. Check SITE_URL and SYNC_KEY. Retrying in {delay}s.")
        except Exception as e:  # noqa: BLE001
            print(f"Cannot reach the website ({e}). Retrying in {delay}s.")
        await asyncio.sleep(delay)
        delay = min(delay * 2, 600)


async def report(code: str, detail: str = ""):
    """Tells the website why the bot is not online, so the admin panel can show it."""
    try:
        async with http.post(
            f"{SITE_URL}/api/public/bot/sync",
            json={"status": code, "detail": detail[:300]},
            headers={"Authorization": f"Bearer {SYNC_KEY}"},
            timeout=aiohttp.ClientTimeout(total=15),
        ):
            pass
    except Exception:  # noqa: BLE001
        pass


async def sleep_reporting(seconds: int, code: str, detail: str = ""):
    """Waits without touching Discord, re-sending the status to the website every 5 minutes."""
    end = time.monotonic() + seconds
    while True:
        await report(code, detail)
        left = end - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(300, left))


async def health_server():
    """Only when the host gives a PORT (e.g. a Render *Web Service*): answer health checks so the
    host does not kill and restart the bot over and over (which would mean repeated Discord logins)."""
    port = os.environ.get("PORT")
    if not port:
        return
    from aiohttp import web

    app = web.Application()
    app.router.add_get("/", lambda _r: web.Response(text="PEAK bot ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    print(f"Health check listening on port {port}")


async def wait_for_new_token(old: str | None) -> str:
    """After Discord rejects a token, never retry it: wait until a different one is saved on the website."""
    while True:
        await report("bad_token" if old else "no_token")
        await asyncio.sleep(300)
        token = os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN")
        if not token or token == old:
            data = await fetch_site_config()
            token = data.get("token")
        if token and token != old:
            return token
        print("Still waiting for a new bot token in the admin panel (checking every 5 minutes).")


async def main():
    global http
    http = aiohttp.ClientSession()
    await health_server()
    # A token configured on the host must not depend on the website being reachable.
    # sync_loop still loads all guild settings as soon as the website responds.
    token = os.environ.get("BOT_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        data = await fetch_site_config()
        for row in data["guilds"]:
            SETTINGS[row["guild_id"]] = row["settings"]
        token = data.get("token")
    asyncio.create_task(report("starting"))
    asyncio.create_task(sync_loop())
    # stats_loop / voice_loop start from on_ready: waiting for "ready" before login crashes them.
    if not token:
        print("No bot token yet. Add it in the website admin panel.")
        token = await wait_for_new_token(None)
    # One login attempt at a time, with long pauses after a failure, so the bot is never flagged
    # for repeated logins. The process stays alive so the host does not restart it in a loop.
    while True:
        try:
            await client.start(token)
            return
        except discord.LoginFailure:
            print("Discord rejected the bot token. Save a new one in the admin panel.")
            bad = token
            await client.close()
            client.clear()
            token = await wait_for_new_token(bad)
        except discord.PrivilegedIntentsRequired:
            print(
                "Discord refused the connection: turn on 'Server Members Intent' and 'Message Content Intent' "
                "in Developer Portal -> Bot -> Privileged Gateway Intents. Trying again in 10 minutes."
            )
            await client.close()
            client.clear()
            await sleep_reporting(600, "intents")
        except discord.HTTPException as e:
            wait = 1800 if e.status == 429 else 300
            print(f"Discord login error {e.status}. Waiting {wait // 60} minutes before trying again.")
            await client.close()
            client.clear()
            await sleep_reporting(wait, "rate_limited" if e.status == 429 else "error", f"Discord error {e.status}")
        except (aiohttp.ClientError, OSError) as e:
            print(f"Network problem ({e}). Retrying in 2 minutes.")
            await client.close()
            client.clear()
            await sleep_reporting(120, "network", str(e))
        except Exception as e:  # noqa: BLE001
            # Never crash: a crash makes the host restart the bot instantly, which means repeated logins.
            print(f"Unexpected error ({e!r}). Waiting 10 minutes before trying again.")
            await client.close()
            client.clear()
            await sleep_reporting(600, "error", repr(e))


if __name__ == "__main__":
    asyncio.run(main())
