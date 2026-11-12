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
import base64
import gzip
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
# Same file as before (peak.db next to the bot) unless DB_PATH points somewhere else, e.g. a mounted disk.
db = sqlite3.connect(os.environ.get("DB_PATH", "peak.db"))
db.executescript(
    """
CREATE TABLE IF NOT EXISTS xp(guild TEXT, user TEXT, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0, PRIMARY KEY(guild,user));
CREATE TABLE IF NOT EXISTS tickets(channel TEXT PRIMARY KEY, guild TEXT, owner TEXT, category TEXT, claimed_by TEXT, opened REAL);
CREATE TABLE IF NOT EXISTS warns(guild TEXT, user TEXT, mod TEXT, reason TEXT, at REAL);
CREATE TABLE IF NOT EXISTS app_cool(guild TEXT, form TEXT, user TEXT, at REAL, PRIMARY KEY(guild,form,user));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS bank(guild TEXT, user TEXT, wallet INTEGER DEFAULT 0, bank INTEGER DEFAULT 0, PRIMARY KEY(guild,user));
CREATE TABLE IF NOT EXISTS bank_cool(guild TEXT, user TEXT, kind TEXT, at REAL, PRIMARY KEY(guild,user,kind));
CREATE TABLE IF NOT EXISTS ticket_seq(guild TEXT PRIMARY KEY, n INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS game_stats(guild TEXT, user TEXT, wins INTEGER DEFAULT 0, PRIMARY KEY(guild,user));
CREATE TABLE IF NOT EXISTS temp_vc(channel TEXT PRIMARY KEY, guild TEXT, owner TEXT, waiting TEXT, created REAL);
"""
)
# Ticket numbers (shown in the closing DM). Adding a column keeps every existing row.
if "num" not in {r[1] for r in db.execute("PRAGMA table_info(tickets)")}:
    db.execute("ALTER TABLE tickets ADD COLUMN num INTEGER")
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
        # Custom emojis, so the dashboard can offer them in its emoji picker.
        "emojis": [{"id": str(e.id), "name": (e.name or "")[:100], "animated": bool(e.animated)} for e in g.emojis][:2000],
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
        try:
            return ImageFont.load_default(size)  # Pillow 10.1+: a scalable built-in font
        except TypeError:
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
    db.execute("DELETE FROM temp_vc WHERE channel=?", (str(ch.id),))
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
    snapshot_soon()  # the dashboard emoji picker shows the new emojis
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

    # auto emoji reactions + auto replies
    if g(s, "autoReact.enabled"):
        start_auto_react(m, s)
    if g(s, "autoReply.enabled"):
        await auto_reply(m, s)

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

    # Games (their own prefix, e.g. -roulette) and the bank (bot prefix) come before the other commands.
    if await handle_help_message(m, s) or await handle_games_message(m, s) or await handle_bank(m, s):
        return
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
    if before.channel != after.channel:
        try:
            await temp_voice_update(member, before.channel, after.channel)
        except discord.HTTPException as e:
            print("temp voice:", e)
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
            await dm_punished(target, guild, s, "ban", author, reason)  # before the ban, or the DM can't arrive
            await target.ban(reason=f"{author}: {reason}", delete_message_days=0)
            await reply(f"🔨 {target} banned")
            await log(guild, "ban", "🔨 Ban (command)", f"{target} by {author.mention}\n{reason}", 0xEF4444)
        elif name == "unban" and args:
            await guild.unban(discord.Object(int(re.sub(r"\D", "", args[0]))))
            await reply("🔓 Unbanned")
        elif name == "kick" and target:
            await dm_punished(target, guild, s, "kick", author, reason)
            await target.kick(reason=f"{author}: {reason}")
            await reply(f"👢 {target} kicked")
            await log(guild, "kick", "👢 Kick (command)", f"{target} by {author.mention}\n{reason}", 0xF97316)
        elif name == "timeout" and target:
            mins = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
            await target.timeout(timedelta(minutes=mins), reason=f"{author}: {' '.join(args[2:])}")
            await reply(f"🔇 {target.mention} timed out {mins}m")
            await dm_punished(target, guild, s, "timeout", author, " ".join(args[2:]) or "No reason", mins)
        elif name == "untimeout" and target:
            await target.timeout(None)
            await reply(f"🔊 {target.mention} un-timed out")
        elif name == "warn" and target:
            db.execute("INSERT INTO warns VALUES (?,?,?,?,?)", (str(guild.id), str(target.id), str(author.id), reason, time.time()))
            db.commit()
            await reply(f"⚠️ {target.mention} warned: {reason}")
            await dm_punished(target, guild, s, "warn", author, reason)
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
def L(s: dict, en: str, ar: str) -> str:
    """Text in the server's bot language (General → Bot language on the website)."""
    return ar if g(s, "general.language", "en") == "ar" else en


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
        await close_ticket(inter)

    @discord.ui.button(label="Add member", style=discord.ButtonStyle.success, custom_id="peak:ticket:add", emoji="➕")
    async def add_member(self, inter: discord.Interaction, _):
        await ticket_member_picker(inter, add=True)

    @discord.ui.button(label="Remove member", style=discord.ButtonStyle.secondary, custom_id="peak:ticket:remove", emoji="➖")
    async def remove_member(self, inter: discord.Interaction, _):
        await ticket_member_picker(inter, add=False)


async def close_ticket(inter: discord.Interaction):
    row = db.execute("SELECT owner, category, claimed_by, opened, num FROM tickets WHERE channel=?", (str(inter.channel.id),)).fetchone()
    if not row:
        return await inter.response.send_message("Not a ticket.", ephemeral=True)
    if not (is_support(inter.user) or str(inter.user.id) == row[0]):
        return await inter.response.send_message("No permission.", ephemeral=True)
    await inter.response.send_message("🔒 Closing in 5 seconds…")
    s = S(inter.guild)
    t = g(s, "tickets", {}) or {}
    dm = t.get("dmOnClose") or {}
    want_dm = bool(dm.get("enabled"))
    want_file = bool(t.get("transcripts")) or (want_dm and dm.get("sendTranscript", True) is not False)
    data = None
    fname = f"transcript-{inter.channel.name}.txt"
    if want_file:
        # Read once and reuse the same text for the archive channel and the DM.
        lines = [f"[{x.created_at:%Y-%m-%d %H:%M}] {x.author}: {x.content}" + "".join(f" [{a.url}]" for a in x.attachments) async for x in inter.channel.history(limit=1000, oldest_first=True)]
        data = "\n".join(lines).encode()
    if t.get("transcripts") and data is not None:
        f = discord.File(io.BytesIO(data), filename=fname)
        tch = channel(inter.guild, t.get("transcriptChannelId"))
        desc = f"Ticket `{inter.channel.name}` · owner <@{row[0]}> · closed by {inter.user.mention}"
        if tch:
            await tch.send(embed=discord.Embed(title="📁 Transcript", description=desc, color=color(s)), file=f)
        else:
            await log(inter.guild, "ticketLogs", "📁 Transcript", desc, file=f)
    if want_dm:
        await dm_ticket_owner(inter, row, s, data if dm.get("sendTranscript", True) is not False else None, fname)
    db.execute("DELETE FROM tickets WHERE channel=?", (str(inter.channel.id),))
    db.commit()
    await asyncio.sleep(5)
    await inter.channel.delete(reason="Ticket closed")


def ticket_dm_embeds(guild: discord.Guild, s: dict, row, closed_by_owner: bool, has_file: bool, fname: str) -> list[discord.Embed]:
    """The summary card the ticket owner gets in DMs when the ticket closes."""
    owner_id, cat_id, claimed_by, opened, num = row
    t = g(s, "tickets", {}) or {}
    cat = next((c for c in t.get("categories", []) if c.get("id") == cat_id), {})
    role_ids = list(dict.fromkeys([*t.get("supportRoles", []), *cat.get("supportRoles", [])]))
    roles = [guild.get_role(int(x)) for x in role_ids if str(x).isdigit()]
    # Role mentions do not display inside DMs, so the role names are written out instead.
    staff = L(s, ", ", "، ").join(f"@{r.name}" for r in roles if r)[:1000]
    msg = str(g(t, "dmOnClose.message", "") or "").strip()[:200] or L(s, "We hope you have a great day!", "نتمنى لك يوماً سعيداً")
    em = discord.Embed(title=f"🎟️ | {L(s, 'Ticket attachments', 'مرفقات التذكرة')}", description=f"💛 : {msg}", color=color(s))
    em.add_field(name=f"📄 : {L(s, 'Ticket number', 'رقم التذكرة')}", value=f"`{num}`" if num else "`-`", inline=False)
    em.add_field(name=f"👑 : {L(s, 'Ticket staff', 'مشرفين التذكرة')}", value=staff or "-", inline=False)
    em.add_field(
        name=f"🛡️ : {L(s, 'Claimed by', 'مسؤول التذكرة')}",
        value=f"<@{claimed_by}>" if claimed_by else L(s, "Nobody claimed the ticket", "لم يتم استلام التذكرة"),
        inline=False,
    )
    em.add_field(name=f"📅 : {L(s, 'Opened at', 'وقت التذكرة')}", value=f"<t:{int(opened)}:f>" if opened else "-", inline=False)
    if has_file:
        em.add_field(name=f"📁 : {L(s, 'Ticket file', 'ملف التذكرة')}", value=f"⬇️ `{fname}`", inline=False)
    em.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
    closed = L(s, "Your ticket was closed by you", "تم قفل تذكرتك من قبلك") if closed_by_owner else L(s, "Your ticket was closed by the staff", "تم قفل تذكرتك من قبل الإدارة")
    em2 = discord.Embed(description=f"💛 : **{msg}**\n🔒 : **{closed}**", color=color(s))
    return [em, em2]


async def dm_ticket_owner(inter: discord.Interaction, row, s: dict, data: bytes | None, fname: str):
    owner_id = int(row[0])
    owner = inter.guild.get_member(owner_id) or client.get_user(owner_id)
    if owner is None:
        try:
            owner = await client.fetch_user(owner_id)
        except discord.HTTPException:
            return
    if owner.bot:
        return
    embeds = ticket_dm_embeds(inter.guild, s, row, str(inter.user.id) == row[0], data is not None, fname)
    try:
        if data is not None:
            await owner.send(embeds=embeds, file=discord.File(io.BytesIO(data), filename=fname))
        else:
            await owner.send(embeds=embeds)
    except discord.HTTPException:
        pass  # the member closed their DMs: nothing else to do


class TicketMemberView(discord.ui.View):
    """Private menu to pick up to 5 people to add to (or remove from) a ticket."""

    def __init__(self, add: bool, owner_id: str, s: dict):
        super().__init__(timeout=120)
        self.add, self.owner_id, self.s = add, owner_id, s
        self.sel = discord.ui.UserSelect(
            placeholder=L(s, "Pick people to add" if add else "Pick people to remove", "اختار الأشخاص للإضافة" if add else "اختار الأشخاص للإزالة"),
            min_values=1,
            max_values=5,
        )
        self.sel.callback = self.picked
        self.add_item(self.sel)

    async def picked(self, inter: discord.Interaction):
        s = self.s
        # Bots are skipped, and the ticket owner can never be removed from their own ticket.
        users = [u for u in self.sel.values if not u.bot and (self.add or str(u.id) != self.owner_id)]
        await inter.response.defer(ephemeral=True)
        done = []
        for u in users[:5]:
            try:
                if self.add:
                    await inter.channel.set_permissions(u, view_channel=True, send_messages=True, attach_files=True, read_message_history=True, reason=f"Ticket: added by {inter.user}")
                else:
                    await inter.channel.set_permissions(u, overwrite=None, reason=f"Ticket: removed by {inter.user}")
                done.append(u.mention)
            except discord.Forbidden:
                await inter.edit_original_response(content=L(s, "❌ I need the Manage Roles permission for that.", "❌ البوت محتاج صلاحية Manage Roles."), view=None)
                return self.stop()
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.5)  # gentle on Discord's limits
        self.stop()
        if done:
            verb = L(s, "added to the ticket by", "انضاف للتذكرة من") if self.add else L(s, "removed from the ticket by", "انشال من التذكرة من")
            await inter.channel.send(f"{'➕' if self.add else '➖'} {', '.join(done)} {verb} {inter.user.mention}")
        await inter.edit_original_response(content="✅" if done else L(s, "Nothing changed.", "ما تغيّر اشي."), view=None)


async def ticket_member_picker(inter: discord.Interaction, add: bool):
    s = S(inter.guild)
    row = db.execute("SELECT owner FROM tickets WHERE channel=?", (str(inter.channel.id),)).fetchone()
    if not row:
        return await inter.response.send_message("Not a ticket.", ephemeral=True)
    if not g(s, "tickets.addMember.enabled"):
        return await inter.response.send_message(L(s, "This option is turned off.", "هالخيار مطفي."), ephemeral=True)
    allowed = is_support(inter.user) or (g(s, "tickets.addMember.who") == "owner" and str(inter.user.id) == row[0])
    if not allowed:
        return await inter.response.send_message("No permission.", ephemeral=True)
    await inter.response.send_message(view=TicketMemberView(add, row[0], s), ephemeral=True)


def is_support(member: discord.Member) -> bool:
    if is_mod(member):
        return True
    t = g(S(member.guild), "tickets", {})
    roles = set(t.get("supportRoles", []))
    for c in t.get("categories", []):
        roles |= set(c.get("supportRoles", []))
    return any(str(r.id) in roles for r in member.roles)


def next_ticket_num(gid: str) -> int:
    db.execute("INSERT INTO ticket_seq(guild, n) VALUES(?, 1) ON CONFLICT(guild) DO UPDATE SET n = n + 1", (gid,))
    return db.execute("SELECT n FROM ticket_seq WHERE guild=?", (gid,)).fetchone()[0]


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
    num = next_ticket_num(str(guild.id))
    db.execute(
        "INSERT INTO tickets(channel, guild, owner, category, claimed_by, opened, num) VALUES (?,?,?,?,?,?,?)",
        (str(ch.id), str(guild.id), str(inter.user.id), cat_id, None, time.time(), num),
    )
    db.commit()
    view = TicketControls()
    labels = {
        "peak:ticket:claim": L(s, "Claim", "استلام"),
        "peak:ticket:close": L(s, "Close", "إغلاق"),
        "peak:ticket:add": L(s, "Add member", "إضافة عضو"),
        "peak:ticket:remove": L(s, "Remove member", "إزالة عضو"),
    }
    for item in list(view.children):
        cid = getattr(item, "custom_id", "")
        if (cid == "peak:ticket:claim" and not t.get("claimEnabled", True)) or (cid in ("peak:ticket:add", "peak:ticket:remove") and not g(t, "addMember.enabled")):
            view.remove_item(item)
        elif cid in labels:
            item.label = labels[cid]
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
    elif cid == "peak:games:panel":
        err = await start_game(inter.channel, inter.user, (inter.data.get("values") or [""])[0], s)
        await inter.response.send_message(f"❌ {err}" if err else "✅", ephemeral=True)
    elif cid.startswith("peak:bank:"):
        await bank_button(inter, cid.split(":")[2], s)
    elif cid.startswith("peak:rr:"):
        await reaction_role_button(inter, cid, s)
    elif cid.startswith("peak:tv:"):
        await tv_button(inter, cid.split(":")[2], s)
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


# ------------------------------------------------------------------ bank
# Every server has its own bank. All money changes happen without an `await` in between, so two
# commands can never spend the same coins twice.
MAX_COINS = 10**15
BANK_WORDS = {
    "balance": "balance", "bal": "balance", "credits": "balance", "رصيد": "balance", "رصيدي": "balance", "فلوس": "balance", "فلوسي": "balance",
    "daily": "daily", "يومي": "daily", "هدية": "daily",
    "work": "work", "راتب": "work", "عمل": "work", "شغل": "work",
    "transfer": "transfer", "pay": "transfer", "تحويل": "transfer", "حول": "transfer", "حوّل": "transfer",
    "deposit": "deposit", "dep": "deposit", "ايداع": "deposit", "إيداع": "deposit", "اودع": "deposit",
    "withdraw": "withdraw", "with": "withdraw", "سحب": "withdraw", "اسحب": "withdraw",
    "rob": "rob", "steal": "rob", "نهب": "rob", "سرقة": "rob", "سرقه": "rob", "اسرق": "rob",
    "bet": "bet", "gamble": "bet", "قمار": "bet", "رهان": "bet",
    "slots": "slots", "slot": "slots", "سلوت": "slots",
    "coinflip": "coinflip", "cf": "coinflip", "flip": "coinflip", "وجه": "coinflip", "قرعة": "coinflip", "قرعه": "coinflip",
    "rich": "rich", "richest": "rich", "baltop": "rich", "الاغنى": "rich", "الأغنى": "rich", "اغنى": "rich", "أغنى": "rich", "اغنياء": "rich",
    "give": "give", "addmoney": "give", "اعطاء": "give", "إعطاء": "give", "اعطي": "give",
    "bank": "menu", "بنك": "menu", "البنك": "menu",
}
WORK_JOBS = [
    ("programmer", "مبرمج"), ("chef", "طباخ"), ("doctor", "دكتور"), ("driver", "سائق"), ("teacher", "أستاذ"),
    ("designer", "مصمم"), ("mechanic", "ميكانيكي"), ("farmer", "مزارع"), ("streamer", "ستريمر"), ("builder", "عامل بناء"),
]
_bank_spam: dict[tuple, float] = {}


def bank_cfg(s: dict) -> dict:
    return g(s, "bank", {}) or {}


def money(s: dict, n: int) -> str:
    return f"**{int(n):,}** {bank_cfg(s).get('currencyEmoji') or '🪙'}"


def account(gid: str, uid: str, s: dict | None = None) -> tuple[int, int]:
    row = db.execute("SELECT wallet, bank FROM bank WHERE guild=? AND user=?", (gid, uid)).fetchone()
    if row:
        return int(row[0]), int(row[1])
    start = max(0, min(MAX_COINS, int(bank_cfg(s or {}).get("startBalance", 0) or 0)))
    db.execute("INSERT OR IGNORE INTO bank(guild, user, wallet, bank) VALUES(?,?,?,0)", (gid, uid, start))
    db.commit()
    return start, 0


def bank_add(gid: str, uid: str, s: dict | None = None, wallet: int = 0, bank: int = 0):
    account(gid, uid, s)
    db.execute(
        "UPDATE bank SET wallet = MIN(?, MAX(0, wallet + ?)), bank = MIN(?, MAX(0, bank + ?)) WHERE guild=? AND user=?",
        (MAX_COINS, int(wallet), MAX_COINS, int(bank), gid, uid),
    )
    db.commit()


def cool_left(gid: str, uid: str, kind: str, seconds: float) -> int:
    row = db.execute("SELECT at FROM bank_cool WHERE guild=? AND user=? AND kind=?", (gid, uid, kind)).fetchone()
    if row and time.time() - row[0] < seconds:
        return int(seconds - (time.time() - row[0])) + 1
    return 0


def cool_set(gid: str, uid: str, kind: str):
    db.execute("INSERT OR REPLACE INTO bank_cool(guild, user, kind, at) VALUES(?,?,?,?)", (gid, uid, kind, time.time()))
    db.commit()


def parse_amount(token: str | None, available: int) -> int | None:
    """100, 1k, 2.5m, all / كل, half / نص."""
    if not token:
        return None
    t = token.lower().replace(",", "").strip()
    if t in ("all", "كل", "الكل", "كلهم", "max"):
        return available
    if t in ("half", "نص", "نصف", "النص"):
        return available // 2
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", t)
    if not m:
        return None
    n = float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2)]
    return int(min(n, MAX_COINS))


def is_bank_admin(member: discord.Member) -> bool:
    if is_mod(member):
        return True
    roles = set(g(S(member.guild), "bank.adminRoles", []))
    return any(str(r.id) in roles for r in member.roles)


def bank_allowed(s: dict, ch) -> bool:
    chans = bank_cfg(s).get("channels") or []
    return not chans or str(getattr(ch, "id", "")) in chans or str(getattr(ch, "parent_id", "")) in chans


def bem(s: dict, text: str, ok: bool = True) -> discord.Embed:
    return discord.Embed(description=text, color=color(s) if ok else 0xEF4444)


def fmt_wait(s: dict, secs: int) -> str:
    return f"<t:{int(time.time() + secs)}:R>"


def act_balance(guild, member, s) -> discord.Embed:
    w, b = account(str(guild.id), str(member.id), s)
    e = discord.Embed(title=f"💰 {member.display_name}", color=color(s))
    e.add_field(name=L(s, "Wallet", "المحفظة"), value=money(s, w)).add_field(name=L(s, "Bank", "البنك"), value=money(s, b))
    e.add_field(name=L(s, "Total", "المجموع"), value=money(s, w + b))
    return e.set_thumbnail(url=member.display_avatar.url)


def act_daily(guild, member, s) -> discord.Embed:
    gid, uid = str(guild.id), str(member.id)
    left = cool_left(gid, uid, "daily", 86400)
    if left:
        return bem(s, L(s, f"⏳ Come back {fmt_wait(s, left)}.", f"⏳ ارجع {fmt_wait(s, left)}."), False)
    amt = max(0, int(bank_cfg(s).get("dailyAmount", 500) or 0))
    bank_add(gid, uid, s, wallet=amt)
    cool_set(gid, uid, "daily")
    return bem(s, L(s, f"🎁 You got your daily {money(s, amt)}!", f"🎁 أخذت هديتك اليومية {money(s, amt)}!"))


def act_work(guild, member, s) -> discord.Embed:
    gid, uid = str(guild.id), str(member.id)
    b = bank_cfg(s)
    cd = max(1, int(b.get("workCooldownMinutes", 60) or 60)) * 60
    left = cool_left(gid, uid, "work", cd)
    if left:
        return bem(s, L(s, f"⏳ You are tired. Work again {fmt_wait(s, left)}.", f"⏳ تعبان! اشتغل مرة ثانية {fmt_wait(s, left)}."), False)
    lo, hi = sorted((max(0, int(b.get("workMin", 50) or 0)), max(0, int(b.get("workMax", 250) or 0))))
    amt = random.randint(lo, hi)
    job = random.choice(WORK_JOBS)
    bank_add(gid, uid, s, wallet=amt)
    cool_set(gid, uid, "work")
    return bem(s, L(s, f"💼 You worked as a **{job[0]}** and earned {money(s, amt)}.", f"💼 اشتغلت **{job[1]}** وأخذت {money(s, amt)}."))


def act_move(guild, member, s, token, to_bank: bool) -> discord.Embed:
    gid, uid = str(guild.id), str(member.id)
    w, b = account(gid, uid, s)
    amt = parse_amount(token, w if to_bank else b)
    if not amt or amt <= 0:
        return bem(s, L(s, "Write an amount, e.g. `100` or `all`.", "اكتب المبلغ، مثلاً `100` أو `كل`."), False)
    if amt > (w if to_bank else b):
        return bem(s, L(s, "You don't have that much.", "ما معك هالمبلغ."), False)
    bank_add(gid, uid, s, wallet=-amt if to_bank else amt, bank=amt if to_bank else -amt)
    return bem(s, (L(s, f"📥 Deposited {money(s, amt)} into the bank.", f"📥 أودعت {money(s, amt)} بالبنك.") if to_bank else L(s, f"📤 Withdrew {money(s, amt)}.", f"📤 سحبت {money(s, amt)}.")))


def check_transfer(guild, member, target, s, token):
    """Returns (error_embed, amount, tax)."""
    if not target or target.bot or target.id == member.id:
        return bem(s, L(s, "Mention who you want to send coins to.", "منشن الشخص اللي بدك تحوله."), False), 0, 0
    w, _ = account(str(guild.id), str(member.id), s)
    amt = parse_amount(token, w)
    if not amt or amt <= 0:
        return bem(s, L(s, "Write an amount, e.g. `100`.", "اكتب المبلغ، مثلاً `100`."), False), 0, 0
    if amt > w:
        return bem(s, L(s, f"Your wallet has only {money(s, w)}.", f"محفظتك فيها بس {money(s, w)}."), False), 0, 0
    tax = int(amt * max(0, min(50, int(bank_cfg(s).get("transferTax", 5) or 0))) / 100)
    return None, amt, tax


def do_transfer(guild, member, target, s, amt: int, tax: int) -> discord.Embed:
    gid = str(guild.id)
    w, _ = account(gid, str(member.id), s)
    if amt > w:  # the wallet changed while the confirm button was waiting
        return bem(s, L(s, "You don't have that much anymore.", "ما عاد معك هالمبلغ."), False)
    bank_add(gid, str(member.id), s, wallet=-amt)
    bank_add(gid, str(target.id), s, wallet=amt - tax)
    return bem(s, L(s, f"💸 {member.mention} sent {money(s, amt - tax)} to {target.mention}" + (f" (tax {money(s, tax)})" if tax else ""), f"💸 {member.mention} حوّل {money(s, amt - tax)} لـ {target.mention}" + (f" (ضريبة {money(s, tax)})" if tax else "")))


def act_rob(guild, member, target, s) -> discord.Embed:
    r = bank_cfg(s).get("rob") or {}
    if not r.get("enabled", True):
        return bem(s, L(s, "Robbing is turned off.", "النهب مطفي."), False)
    if not target or target.bot or target.id == member.id:
        return bem(s, L(s, "Mention who you want to rob.", "منشن الشخص اللي بدك تنهبه."), False)
    gid, uid = str(guild.id), str(member.id)
    cd = max(5, int(r.get("cooldownMinutes", 120) or 120)) * 60
    left = cool_left(gid, uid, "rob", cd)
    if left:
        return bem(s, L(s, f"🚓 The police are watching you. Try {fmt_wait(s, left)}.", f"🚓 الشرطة عينها عليك. جرب {fmt_wait(s, left)}."), False)
    tw, _ = account(gid, str(target.id), s)
    if tw < 100:
        return bem(s, L(s, "Their wallet is almost empty, not worth it.", "محفظته شبه فاضية، ما بتستاهل."), False)
    cool_set(gid, uid, "rob")
    if random.randint(1, 100) <= max(1, min(90, int(r.get("chance", 40) or 40))):
        amt = max(1, int(tw * random.randint(5, max(5, min(100, int(r.get("maxPercent", 20) or 20)))) / 100))
        bank_add(gid, str(target.id), s, wallet=-amt)
        bank_add(gid, uid, s, wallet=amt)
        return bem(s, L(s, f"🦹 You robbed {money(s, amt)} from {target.mention}!", f"🦹 نهبت {money(s, amt)} من {target.mention}!"))
    w, _ = account(gid, uid, s)
    fine = int(w * max(0, min(100, int(r.get("fine", 10) or 0))) / 100)
    if fine:
        bank_add(gid, uid, s, wallet=-fine)
        bank_add(gid, str(target.id), s, wallet=fine)
    return bem(s, L(s, f"🚨 You got caught! You paid {money(s, fine)} to {target.mention}.", f"🚨 انمسكت! دفعت {money(s, fine)} لـ {target.mention}."), False)


def _bet_amount(guild, member, s, token):
    gm = bank_cfg(s).get("gamble") or {}
    if not gm.get("enabled", True):
        return bem(s, L(s, "Gambling is turned off.", "القمار مطفي."), False), 0
    w, _ = account(str(guild.id), str(member.id), s)
    amt = parse_amount(token, min(w, int(gm.get("maxBet", 10000) or 10000)))
    if not amt or amt <= 0:
        return bem(s, L(s, "Write a bet, e.g. `100` or `all`.", "اكتب الرهان، مثلاً `100` أو `كل`."), False), 0
    if amt > w:
        return bem(s, L(s, "You don't have that much in your wallet.", "ما معك هالمبلغ بالمحفظة."), False), 0
    mx = int(gm.get("maxBet", 10000) or 10000)
    if amt > mx:
        return bem(s, L(s, f"The max bet is {money(s, mx)}.", f"أقصى رهان {money(s, mx)}."), False), 0
    return None, amt


def act_bet(guild, member, s, token) -> discord.Embed:
    err, amt = _bet_amount(guild, member, s, token)
    if err:
        return err
    gid, uid = str(guild.id), str(member.id)
    if random.random() < 0.48:
        bank_add(gid, uid, s, wallet=amt)
        return bem(s, L(s, f"🎉 You won {money(s, amt)}!", f"🎉 ربحت {money(s, amt)}!"))
    bank_add(gid, uid, s, wallet=-amt)
    return bem(s, L(s, f"💸 You lost {money(s, amt)}.", f"💸 خسرت {money(s, amt)}."), False)


SLOT_ICONS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]


def act_slots(guild, member, s, token) -> discord.Embed:
    err, amt = _bet_amount(guild, member, s, token)
    if err:
        return err
    gid, uid = str(guild.id), str(member.id)
    reel = [random.choice(SLOT_ICONS) for _ in range(3)]
    line = " | ".join(reel)
    if reel[0] == reel[1] == reel[2]:
        win = amt * (10 if reel[0] == "7️⃣" else 5)
        bank_add(gid, uid, s, wallet=win - amt)
        return bem(s, f"🎰 {line}\n" + L(s, f"JACKPOT! You won {money(s, win)}!", f"جاكبوت! ربحت {money(s, win)}!"))
    if len(set(reel)) == 2:
        bank_add(gid, uid, s, wallet=amt)
        return bem(s, f"🎰 {line}\n" + L(s, f"Nice! You won {money(s, amt * 2)}.", f"حلو! ربحت {money(s, amt * 2)}."))
    bank_add(gid, uid, s, wallet=-amt)
    return bem(s, f"🎰 {line}\n" + L(s, f"You lost {money(s, amt)}.", f"خسرت {money(s, amt)}."), False)


def act_coinflip(guild, member, s, token, side: str | None) -> discord.Embed:
    err, amt = _bet_amount(guild, member, s, token)
    if err:
        return err
    gid, uid = str(guild.id), str(member.id)
    pick = "heads" if (side or "").lower() in ("", "h", "heads", "ملك", "وجه") else "tails"
    res = random.choice(["heads", "tails"])
    face = {"heads": L(s, "Heads", "ملك"), "tails": L(s, "Tails", "كتابة")}[res]
    if res == pick:
        bank_add(gid, uid, s, wallet=amt)
        return bem(s, f"🪙 {face}! " + L(s, f"You won {money(s, amt)}.", f"ربحت {money(s, amt)}."))
    bank_add(gid, uid, s, wallet=-amt)
    return bem(s, f"🪙 {face}! " + L(s, f"You lost {money(s, amt)}.", f"خسرت {money(s, amt)}."), False)


def act_rich(guild, s) -> discord.Embed:
    rows = db.execute("SELECT user, wallet + bank AS t FROM bank WHERE guild=? AND wallet + bank > 0 ORDER BY t DESC LIMIT 10", (str(guild.id),)).fetchall()
    medals = ["🥇", "🥈", "🥉"]
    desc = "\n".join(f"{medals[i] if i < 3 else f'**{i + 1}.**'} <@{u}> — {money(s, t)}" for i, (u, t) in enumerate(rows))
    return discord.Embed(title=L(s, "🏆 Richest members", "🏆 أغنى الأعضاء"), description=desc or L(s, "Nobody has coins yet.", "ما حدا معه فلوس لسا."), color=color(s))


def act_give(guild, member, target, s, token) -> discord.Embed:
    if not is_bank_admin(member):
        return bem(s, L(s, "Bank admins only.", "لإدارة البنك بس."), False)
    if not target or target.bot:
        return bem(s, L(s, "Mention a member.", "منشن عضو."), False)
    neg = bool(token and token.startswith("-"))
    amt = parse_amount(token.lstrip("-") if token else None, MAX_COINS)
    if not amt:
        return bem(s, L(s, "Write an amount, e.g. `500` or `-500`.", "اكتب المبلغ، مثلاً `500` أو `-500`."), False)
    bank_add(str(guild.id), str(target.id), s, wallet=-amt if neg else amt)
    return bem(s, L(s, f"{'➖ Took' if neg else '➕ Gave'} {money(s, amt)} {'from' if neg else 'to'} {target.mention}.", f"{'➖ سحبت' if neg else '➕ أعطيت'} {money(s, amt)} {'من' if neg else 'لـ'} {target.mention}."))


class ConfirmTransfer(discord.ui.View):
    def __init__(self, member, target, s, amt, tax):
        super().__init__(timeout=30)
        self.member, self.target, self.s, self.amt, self.tax = member, target, s, amt, tax
        yes = discord.ui.Button(label=L(s, "Confirm", "تأكيد"), style=discord.ButtonStyle.success, emoji="✅")
        no = discord.ui.Button(label=L(s, "Cancel", "إلغاء"), style=discord.ButtonStyle.secondary)
        yes.callback, no.callback = self.yes, self.no
        self.add_item(yes)
        self.add_item(no)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.member.id:
            await inter.response.send_message(L(self.s, "This is not your transfer.", "هاد مش تحويلك."), ephemeral=True)
            return False
        return True

    async def yes(self, inter: discord.Interaction):
        self.stop()
        await inter.response.edit_message(embed=do_transfer(inter.guild, self.member, self.target, self.s, self.amt, self.tax), view=None)

    async def no(self, inter: discord.Interaction):
        self.stop()
        await inter.response.edit_message(embed=bem(self.s, L(self.s, "Transfer cancelled.", "انلغى التحويل."), False), view=None)


def transfer_prompt(s, member, target, amt, tax) -> discord.Embed:
    return bem(s, L(s, f"Send {money(s, amt - tax)} to {target.mention}?" + (f" (tax {money(s, tax)})" if tax else ""), f"تحوّل {money(s, amt - tax)} لـ {target.mention}؟" + (f" (ضريبة {money(s, tax)})" if tax else "")))


def bank_menu_view(s: dict) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for row, items in enumerate((
        (("balance", L(s, "Balance", "رصيدي"), "💰", discord.ButtonStyle.primary), ("daily", L(s, "Daily", "يومي"), "🎁", discord.ButtonStyle.success), ("work", L(s, "Work", "راتب"), "💼", discord.ButtonStyle.secondary)),
        (("deposit", L(s, "Deposit", "إيداع"), "📥", discord.ButtonStyle.secondary), ("withdraw", L(s, "Withdraw", "سحب"), "📤", discord.ButtonStyle.secondary), ("transfer", L(s, "Transfer", "تحويل"), "💸", discord.ButtonStyle.secondary), ("top", L(s, "Richest", "الأغنى"), "🏆", discord.ButtonStyle.secondary)),
    )):
        for key, label, emoji, style in items:
            v.add_item(discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"peak:bank:{key}", row=row))
    return v


def bank_menu_embed(s: dict) -> discord.Embed:
    return discord.Embed(title=f"🏦 {L(s, 'PEAK Bank', 'بنك PEAK')}", description=L(s, "Use the buttons below to manage your money.", "استخدم الأزرار تحت عشان تدير فلوسك."), color=color(s))


async def handle_bank(m: discord.Message, s: dict) -> bool:
    """Prefix bank commands. Returns True when the message was a bank command."""
    b = bank_cfg(s)
    if not b.get("enabled"):
        return False
    prefix = g(s, "general.prefix", "!") or "!"
    if not m.content.startswith(prefix):
        return False
    parts = m.content[len(prefix):].split()
    if not parts:
        return False
    action = BANK_WORDS.get(parts[0].lower())
    if not action:
        return False
    if not bank_allowed(s, m.channel):
        return True
    key = (m.guild.id, m.author.id)
    if time.monotonic() - _bank_spam.get(key, 0) < 2.5:  # one bank command every 2.5s per member
        return True
    _bank_spam[key] = time.monotonic()
    args = parts[1:]
    guild, me = m.guild, m.author
    target = next((x for x in m.mentions if isinstance(x, discord.Member)), None) or (parse_member(guild, args[0]) if args else None)
    num = next((a for a in args if not re.fullmatch(r"<@!?\d+>", a) and not (a.isdigit() and len(a) >= 15)), None)
    try:
        if action == "balance":
            await m.channel.send(embed=act_balance(guild, target or me, s))
        elif action == "daily":
            await m.channel.send(embed=act_daily(guild, me, s))
        elif action == "work":
            await m.channel.send(embed=act_work(guild, me, s))
        elif action in ("deposit", "withdraw"):
            await m.channel.send(embed=act_move(guild, me, s, num, action == "deposit"))
        elif action == "transfer":
            err, amt, tax = check_transfer(guild, me, target, s, num)
            if err:
                await m.channel.send(embed=err)
            else:
                await m.channel.send(embed=transfer_prompt(s, me, target, amt, tax), view=ConfirmTransfer(me, target, s, amt, tax))
        elif action == "rob":
            await m.channel.send(embed=act_rob(guild, me, target, s))
        elif action == "bet":
            await m.channel.send(embed=act_bet(guild, me, s, num))
        elif action == "slots":
            await m.channel.send(embed=act_slots(guild, me, s, num))
        elif action == "coinflip":
            side = next((a for a in args if a.lower() in ("h", "t", "heads", "tails", "ملك", "كتابة", "وجه")), None)
            await m.channel.send(embed=act_coinflip(guild, me, s, next((a for a in args if a != side), None), side))
        elif action == "rich":
            await m.channel.send(embed=act_rich(guild, s))
        elif action == "give":
            await m.channel.send(embed=act_give(guild, me, target, s, num))
        elif action == "menu":
            await m.channel.send(embed=bank_menu_embed(s), view=bank_menu_view(s))
    except discord.HTTPException:
        pass
    return True


class AmountModal(discord.ui.Modal):
    def __init__(self, s: dict, kind: str, target: discord.Member | None = None):
        title = {"deposit": L(s, "Deposit", "إيداع"), "withdraw": L(s, "Withdraw", "سحب"), "transfer": L(s, "Transfer", "تحويل")}[kind]
        super().__init__(title=title)
        self.s, self.kind, self.target = s, kind, target
        self.amount = discord.ui.TextInput(label=L(s, "Amount (number or all)", "المبلغ (رقم أو كل)"), max_length=20)
        self.add_item(self.amount)

    async def on_submit(self, inter: discord.Interaction):
        s = self.s
        if self.kind == "transfer":
            err, amt, tax = check_transfer(inter.guild, inter.user, self.target, s, str(self.amount.value))
            em = err or do_transfer(inter.guild, inter.user, self.target, s, amt, tax)
        else:
            em = act_move(inter.guild, inter.user, s, str(self.amount.value), self.kind == "deposit")
        await inter.response.send_message(embed=em, ephemeral=True)


class TransferPick(discord.ui.View):
    def __init__(self, s: dict):
        super().__init__(timeout=60)
        self.s = s
        self.sel = discord.ui.UserSelect(placeholder=L(s, "Who do you want to send coins to?", "لمين بدك تحوّل؟"), min_values=1, max_values=1)
        self.sel.callback = self.picked
        self.add_item(self.sel)

    async def picked(self, inter: discord.Interaction):
        target = self.sel.values[0]
        self.stop()
        if target.bot or target.id == inter.user.id:
            return await inter.response.send_message(embed=bem(self.s, L(self.s, "Pick another member.", "اختار عضو ثاني."), False), ephemeral=True)
        await inter.response.send_modal(AmountModal(self.s, "transfer", target))


async def bank_button(inter: discord.Interaction, key: str, s: dict):
    if not bank_cfg(s).get("enabled"):
        return await inter.response.send_message(L(s, "The bank is turned off.", "البنك مطفي."), ephemeral=True)
    if not bank_allowed(s, inter.channel):
        return await inter.response.send_message(L(s, "The bank is not available in this channel.", "البنك مش متاح بهالروم."), ephemeral=True)
    guild, me = inter.guild, inter.user
    if key == "balance":
        await inter.response.send_message(embed=act_balance(guild, me, s), ephemeral=True)
    elif key == "daily":
        await inter.response.send_message(embed=act_daily(guild, me, s), ephemeral=True)
    elif key == "work":
        await inter.response.send_message(embed=act_work(guild, me, s), ephemeral=True)
    elif key == "top":
        await inter.response.send_message(embed=act_rich(guild, s), ephemeral=True)
    elif key in ("deposit", "withdraw"):
        await inter.response.send_modal(AmountModal(s, key))
    elif key == "transfer":
        await inter.response.send_message(view=TransferPick(s), ephemeral=True)
    else:
        await inter.response.send_message("?", ephemeral=True)


async def interest_loop():
    """Once a day, adds the interest to money kept in the bank (local only, no Discord calls)."""
    await client.wait_until_ready()
    while True:
        try:
            for guild in client.guilds:
                b = bank_cfg(S(guild))
                if not (b.get("enabled") and g(b, "interest.enabled")):
                    continue
                key = f"interest:{guild.id}"
                row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
                if row and time.time() - float(row[0]) < 86400:
                    continue
                pct = max(1, min(10, int(g(b, "interest.percent", 1) or 1)))
                db.execute("UPDATE bank SET bank = MIN(?, bank + MIN(1000000, CAST(bank * ? / 100 AS INTEGER))) WHERE guild=? AND bank > 0", (MAX_COINS, pct, str(guild.id)))
                db.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (key, str(time.time())))
                db.commit()
        except Exception as e:  # noqa: BLE001
            print("interest failed:", e)
        await asyncio.sleep(3600)


@tree.command(name="balance", description="Show your PEAK bank balance")
@app_commands.guild_only()
async def slash_balance(inter: discord.Interaction, member: discord.Member | None = None):
    s = S(inter.guild)
    if not bank_cfg(s).get("enabled"):
        return await inter.response.send_message(L(s, "The bank is turned off.", "البنك مطفي."), ephemeral=True)
    await inter.response.send_message(embed=act_balance(inter.guild, member or inter.user, s))


@tree.command(name="daily", description="Get your daily coins")
@app_commands.guild_only()
async def slash_daily(inter: discord.Interaction):
    await bank_button(inter, "daily", S(inter.guild))


@tree.command(name="work", description="Work for coins")
@app_commands.guild_only()
async def slash_work(inter: discord.Interaction):
    await bank_button(inter, "work", S(inter.guild))


@tree.command(name="transfer", description="Send coins to a member")
@app_commands.guild_only()
async def slash_transfer(inter: discord.Interaction, member: discord.Member, amount: str):
    s = S(inter.guild)
    if not bank_cfg(s).get("enabled"):
        return await inter.response.send_message(L(s, "The bank is turned off.", "البنك مطفي."), ephemeral=True)
    err, amt, tax = check_transfer(inter.guild, inter.user, member, s, amount)
    if err:
        return await inter.response.send_message(embed=err, ephemeral=True)
    await inter.response.send_message(embed=transfer_prompt(s, inter.user, member, amt, tax), view=ConfirmTransfer(inter.user, member, s, amt, tax))


@tree.command(name="bank", description="Open the PEAK bank menu")
@app_commands.guild_only()
async def slash_bank(inter: discord.Interaction):
    s = S(inter.guild)
    if not bank_cfg(s).get("enabled"):
        return await inter.response.send_message(L(s, "The bank is turned off.", "البنك مطفي."), ephemeral=True)
    await inter.response.send_message(embed=bank_menu_embed(s), view=bank_menu_view(s))


@tree.command(name="rich", description="Richest members of this server")
@app_commands.guild_only()
async def slash_rich(inter: discord.Interaction):
    await bank_button(inter, "top", S(inter.guild))


# ------------------------------------------------------------------ games
# PEAK's own games. One game per channel, at most 3 big games per server, and every round waits a few
# seconds, so a busy game night never floods Discord. Button clicks are answered by editing the
# message through the click itself, which costs no extra Discord API call.
GAME_INFO = {
    # id: (emoji, English, Arabic, kind, min players)
    "roulette": ("🎡", "Roulette", "روليت", "server", 4),
    "mafia": ("🕵️", "Mafia", "مافيا", "server", 5),
    "chairs": ("🪑", "Chairs", "كراسي", "server", 3),
    "rps": ("✂️", "Rock Paper Scissors", "حجرة ورقة مقص", "server", 2),
    "dice": ("🎲", "Dice", "نرد", "server", 2),
    "deathwheel": ("☠️", "Death Wheel", "عجلة الموت", "server", 3),
    "bomb": ("💣", "Bomb", "قنبلة", "server", 3),
    "xo": ("❌", "XO", "اكس او", "duel", 2),
    "hotxo": ("🔥", "Hot XO", "اكس او نار", "duel", 2),
    "fast": ("⚡", "Fast Type", "اسرع", "mini", 1),
    "reverse": ("🔁", "Text Reverse", "اعكس", "mini", 1),
    "split": ("✂️", "Text Split", "فكك", "mini", 1),
    "merge": ("🔗", "Merge Text", "ركب", "mini", 1),
    "flag": ("🚩", "Guess the Flag", "اعلام", "mini", 1),
    "capital": ("🏛️", "Capitals", "عواصم", "mini", 1),
    "math": ("➗", "Math", "حساب", "mini", 1),
    "sort": ("🔢", "Sort Numbers", "رتب", "mini", 1),
    "emoji": ("😀", "Count the Emoji", "ايموجي", "mini", 1),
}
GAME_RULES = {
    "roulette": ("Each round the wheel picks a player, and they choose who gets kicked. Last one standing wins.", "كل جولة العجلة بتختار لاعب، وهو بيختار مين يطلع. آخر واحد بيضل هو الفايز."),
    "mafia": ("Mafia kill at night, the doctor saves, the detective investigates. The town votes by day.", "المافيا بتقتل بالليل، الدكتور بيحمي، المحقق بيكشف، والمدينة بتصوّت بالنهار."),
    "chairs": ("When the music stops, grab a chair! Some chairs are traps. No chair = out.", "لما توقف الموسيقى امسك كرسي! في كراسي فخ. اللي ما بلاقي كرسي بيطلع."),
    "rps": ("Pick rock, paper or scissors against PEAK. Losers drop out each round.", "اختار حجرة أو ورقة أو مقص ضد البوت. الخسران بيطلع كل جولة."),
    "dice": ("Two teams, three rounds. Roll the dice; the highest team total wins the round.", "فريقين و3 جولات. ارمي النرد، والفريق صاحب المجموع الأعلى بيفوز."),
    "deathwheel": ("The wheel picks you, then you pick a box… and hope.", "العجلة بتختارك، وبعدين بتختار صندوق… وادعي."),
    "bomb": ("Pass the bomb before it explodes! Whoever holds it at the boom is out.", "مرّر القنبلة قبل ما تنفجر! اللي بتنفجر معه بيطلع."),
}
SERVER_GAMES = {k for k, v in GAME_INFO.items() if v[3] == "server"}
GAME_WORDS: dict[str, str] = {}
STOP_WORDS = {"stop", "ايقاف", "إيقاف", "وقف", "قف", "stopgame"}
RUNNING: dict[int, "BaseGame"] = {}
_game_spam: dict[tuple, float] = {}
ZW_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
AR_DIAC = re.compile("[\u064b-\u0652\u0640]")


def norm(text: str) -> str:
    t = AR_DIAC.sub("", (text or "").strip().lower())
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي").replace(",", " ").replace("،", " ")
    return re.sub(r"\s+", " ", t).strip()


def canon(text: str) -> str:
    """Looser match for names: also ignores a leading 'ال'."""
    return " ".join(w[2:] if w.startswith("ال") and len(w) > 3 else w for w in norm(text).split())


for _gid, (_e, _en, _ar, _k, _m) in GAME_INFO.items():
    GAME_WORDS[norm(_gid)] = _gid
    GAME_WORDS[norm(_ar.split()[0])] = _gid
    GAME_WORDS[norm(_ar.replace(" ", ""))] = _gid
for _w, _gid in {
    "roulette": "roulette", "عجله": "deathwheel", "عجلة": "deathwheel", "wheel": "deathwheel", "death": "deathwheel",
    "حجره": "rps", "حجرة": "rps", "rock": "rps", "بومب": "bomb", "قنبله": "bomb", "اكس": "xo", "xo": "xo", "tictactoe": "xo",
    "نار": "hotxo", "hot": "hotxo", "اسرع": "fast", "fasttype": "fast", "type": "fast", "عكس": "reverse", "فكك": "split",
    "ركب": "merge", "علم": "flag", "اعلام": "flag", "flags": "flag", "عاصمه": "capital", "عواصم": "capital",
    "capitals": "capital", "حساب": "math", "رياضيات": "math", "رتب": "sort", "ترتيب": "sort", "emojis": "emoji", "كراسي": "chairs",
}.items():
    GAME_WORDS[norm(_w)] = _gid


def gname(s: dict, gid: str) -> str:
    e, en, ar, _, _ = GAME_INFO[gid]
    return f"{e} {L(s, en, ar)}"


def games_cfg(s: dict) -> dict:
    return g(s, "games", {}) or {}


def can_manage_games(member: discord.Member, s: dict) -> bool:
    roles = set(games_cfg(s).get("managerRoles") or [])
    return not roles or is_mod(member) or any(str(r.id) in roles for r in member.roles)


def games_allowed(s: dict, ch) -> bool:
    chans = games_cfg(s).get("channels") or []
    return not chans or str(ch.id) in chans


class BaseGame:
    min_players = 2

    def __init__(self, ch, starter: discord.Member, s: dict, gid: str, opponent: discord.Member | None = None):
        self.channel, self.starter, self.s, self.gid, self.opponent = ch, starter, s, gid, opponent
        self.guild_id = ch.guild.id
        self.players: list[discord.Member] = []
        self.views: list[discord.ui.View] = []
        self.task: asyncio.Task | None = None
        self.min_players = GAME_INFO[gid][4]

    def t(self, en: str, ar: str) -> str:
        return L(self.s, en, ar)

    @property
    def title(self) -> str:
        return gname(self.s, self.gid)

    def track(self, v):
        self.views.append(v)
        return v

    def embed(self, desc: str, title: str | None = None, col: int | None = None) -> discord.Embed:
        return discord.Embed(title=title if title is not None else self.title, description=desc[:4000], color=col if col is not None else color(self.s))

    async def send(self, **kw):
        kw.setdefault("allowed_mentions", discord.AllowedMentions(everyone=False, roles=False, users=True))
        return await self.channel.send(**kw)

    async def safe_run(self):
        try:
            await self.run()
        except asyncio.CancelledError:
            pass
        except discord.HTTPException as e:
            print(f"game {self.gid} stopped by a Discord error: {e.status}")
        except Exception as e:  # noqa: BLE001
            print(f"game {self.gid} crashed: {e!r}")
        finally:
            for v in self.views:
                v.stop()
            if RUNNING.get(self.channel.id) is self:
                RUNNING.pop(self.channel.id, None)

    async def run(self):
        raise NotImplementedError

    # ---- lobby
    def lobby_embed(self, end: float, closed: bool = False) -> discord.Embed:
        mx = max(4, min(25, int(games_cfg(self.s).get("maxPlayers", 20) or 20)))
        names = " ".join(f"`{i + 1}` {p.mention}" for i, p in enumerate(self.players)) or "—"
        rules = GAME_RULES.get(self.gid, ("", ""))
        status = self.t("⏳ Starting…", "⏳ بلشت…") if closed else self.t(f"⏳ Starts <t:{int(end)}:R>", f"⏳ بتبدأ <t:{int(end)}:R>")
        return self.embed(f"{self.t(*rules)}\n\n👥 **{self.t('Players', 'اللاعبين')} ({len(self.players)}/{mx})**\n{names}\n\n{status}")

    async def lobby(self) -> bool:
        secs = max(15, min(120, int(games_cfg(self.s).get("lobbySeconds", 30) or 30)))
        end = time.time() + secs
        view = self.track(LobbyView(self, end))
        msg = await self.send(embed=self.lobby_embed(end), view=view)
        try:
            await asyncio.wait_for(view.go.wait(), timeout=secs)
        except asyncio.TimeoutError:
            pass
        view.stop()
        try:
            await msg.edit(embed=self.lobby_embed(end, closed=True), view=None)
        except discord.HTTPException:
            pass
        if len(self.players) < self.min_players:
            await self.send(embed=self.embed(self.t(f"❌ Not enough players ({len(self.players)}/{self.min_players}).", f"❌ ما في لاعبين كفاية ({len(self.players)}/{self.min_players})."), col=0xEF4444))
            return False
        await asyncio.sleep(2)
        return True

    async def win(self, winners: list, extra: str = ""):
        gs = games_cfg(self.s)
        coins = int((gs.get("miniCoins", 20) if GAME_INFO[self.gid][3] == "mini" else gs.get("winnerCoins", 100)) or 0)
        bank_on = bool(bank_cfg(self.s).get("enabled")) and coins > 0
        gid = str(self.guild_id)
        for w in winners:
            db.execute("INSERT INTO game_stats(guild, user, wins) VALUES(?,?,1) ON CONFLICT(guild, user) DO UPDATE SET wins = wins + 1", (gid, str(w.id)))
            if bank_on:
                bank_add(gid, str(w.id), self.s, wallet=coins)
        db.commit()
        text = f"🏆 {' '.join(w.mention for w in winners)} {self.t('won!', 'فاز!') if len(winners) == 1 else self.t('won!', 'فازوا!')}"
        if bank_on:
            text += f"\n+{money(self.s, coins)}"
        if extra:
            text += f"\n{extra}"
        await self.send(embed=self.embed(text, col=0xFACC15))


class LobbyView(discord.ui.View):
    def __init__(self, game: BaseGame, end: float):
        super().__init__(timeout=200)
        self.game, self.end = game, end
        self.go = asyncio.Event()
        s = game.s
        for label, emoji, style, cb in (
            (L(s, "Join", "انضمام"), "✅", discord.ButtonStyle.success, self.join),
            (L(s, "Leave", "خروج"), "🚪", discord.ButtonStyle.secondary, self.leave),
            (L(s, "Start now", "ابدأ هلأ"), "▶️", discord.ButtonStyle.primary, self.start),
        ):
            b = discord.ui.Button(label=label, emoji=emoji, style=style)
            b.callback = cb
            self.add_item(b)

    async def join(self, inter: discord.Interaction):
        gm = self.game
        mx = max(4, min(25, int(games_cfg(gm.s).get("maxPlayers", 20) or 20)))
        if self.go.is_set():
            return await inter.response.send_message(gm.t("The game already started.", "اللعبة بلشت."), ephemeral=True)
        if any(p.id == inter.user.id for p in gm.players):
            return await inter.response.send_message(gm.t("You already joined.", "انت منضم أصلاً."), ephemeral=True)
        if len(gm.players) >= mx:
            return await inter.response.send_message(gm.t("The game is full.", "اللعبة مليانة."), ephemeral=True)
        gm.players.append(inter.user)
        await inter.response.edit_message(embed=gm.lobby_embed(self.end), view=self)
        if len(gm.players) >= mx:
            self.go.set()

    async def leave(self, inter: discord.Interaction):
        gm = self.game
        if self.go.is_set() or not any(p.id == inter.user.id for p in gm.players):
            return await inter.response.send_message(gm.t("You are not in the game.", "انت مش باللعبة."), ephemeral=True)
        gm.players = [p for p in gm.players if p.id != inter.user.id]
        await inter.response.edit_message(embed=gm.lobby_embed(self.end), view=self)

    async def start(self, inter: discord.Interaction):
        gm = self.game
        if inter.user.id != gm.starter.id and not can_manage_games(inter.user, gm.s):
            return await inter.response.send_message(gm.t("Only the one who started the game can do that.", "بس اللي بلّش اللعبة بقدر."), ephemeral=True)
        if len(gm.players) < gm.min_players:
            return await inter.response.send_message(gm.t(f"At least {gm.min_players} players are needed.", f"لازم {gm.min_players} لاعبين عالأقل."), ephemeral=True)
        await inter.response.defer()
        self.go.set()


class PickView(discord.ui.View):
    """One player (the chooser) picks one of `options`. Extra buttons: (key, label, emoji)."""

    def __init__(self, game: BaseGame, chooser, options: list, labels: dict | None = None, extras=(), timeout: float = 20):
        super().__init__(timeout=timeout)
        self.game, self.chooser = game, chooser
        self.result = None
        self.inter: discord.Interaction | None = None
        if len(options) <= 20:
            for i, p in enumerate(options):
                b = discord.ui.Button(label=((labels or {}).get(p.id) or p.display_name)[:80], style=discord.ButtonStyle.secondary, row=i // 5)
                b.callback = self._mk(p)
                self.add_item(b)
        else:
            sel = discord.ui.Select(options=[discord.SelectOption(label=((labels or {}).get(p.id) or p.display_name)[:100], value=str(p.id)) for p in options[:25]], row=0)
            pmap = {str(p.id): p for p in options}

            async def picked(inter: discord.Interaction):
                await self._done(inter, pmap.get(sel.values[0]))

            sel.callback = picked
            self.add_item(sel)
        for key, label, emoji in extras:
            b = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.danger if key == "withdraw" else discord.ButtonStyle.primary, row=4)
            b.callback = self._mk(key)
            self.add_item(b)

    def _mk(self, value):
        async def cb(inter: discord.Interaction):
            await self._done(inter, value)
        return cb

    async def _done(self, inter, value):
        self.result, self.inter = value, inter
        self.stop()

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.chooser.id:
            await inter.response.send_message(self.game.t("It's not your turn.", "مش دورك."), ephemeral=True)
            return False
        return True


async def finish(view, msg, embed: discord.Embed):
    """Shows the round result on the round message: through the click when there was one (no extra call)."""
    try:
        if view.inter and not view.inter.response.is_done():
            await view.inter.response.edit_message(embed=embed, view=None)
        else:
            await msg.edit(embed=embed, view=None)
    except discord.HTTPException:
        pass


WHEEL_COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6", "#f43f5e"]


def wheel_image(labels: list[str], chosen: int) -> discord.File:
    """A wheel with numbered slices, turned so the chosen slice sits under the arrow."""
    import math

    W = 520
    img = Image.new("RGBA", (W, W), (15, 18, 28, 255))
    d = ImageDraw.Draw(img)
    cx = cy = W // 2
    r = 230
    n = max(1, len(labels))
    seg = 360 / n
    off = -90 - (chosen + 0.5) * seg
    for i in range(n):
        d.pieslice((cx - r, cy - r, cx + r, cy + r), off + i * seg, off + (i + 1) * seg, fill=WHEEL_COLORS[i % len(WHEEL_COLORS)], outline=(15, 18, 28), width=3)
    f = font(28 if n <= 12 else 20)
    for i, lab in enumerate(labels):
        a = math.radians(off + (i + 0.5) * seg)
        d.text((cx + math.cos(a) * r * 0.72, cy + math.sin(a) * r * 0.72), lab, font=f, fill="white", anchor="mm", stroke_width=2, stroke_fill=(15, 18, 28))
    d.ellipse((cx - 55, cy - 55, cx + 55, cy + 55), fill=(15, 18, 28), outline="white", width=4)
    d.text((cx, cy), labels[chosen] if labels else "", font=font(44), fill="white", anchor="mm")
    d.polygon([(cx - 22, 2), (cx + 22, 2), (cx, 44)], fill="white", outline=(15, 18, 28))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return discord.File(buf, filename="wheel.png")


class Roulette(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        num = {p.id: i + 1 for i, p in enumerate(self.players)}
        alive = list(self.players)
        while len(alive) > 1:
            chosen = random.choice(alive)
            labels = [str(num[p.id]) for p in alive]
            file = wheel_image(labels, alive.index(chosen))
            if len(alive) == 2:
                await self.send(embed=self.embed(self.t(f"🎡 The wheel picked {chosen.mention}!", f"🎡 العجلة اختارت {chosen.mention}!")).set_image(url="attachment://wheel.png"), file=file)
                await asyncio.sleep(2)
                return await self.win([chosen])
            others = [p for p in alive if p.id != chosen.id]
            view = self.track(PickView(
                self, chosen, others, {p.id: f"{num[p.id]}. {p.display_name}" for p in others},
                extras=(("random", self.t("Random", "عشوائي"), "🎲"), ("withdraw", self.t("Withdraw", "انسحاب"), "🏳️")),
            ))
            em = self.embed(self.t(f"🎡 {chosen.mention}, choose who gets kicked! (20s)", f"🎡 {chosen.mention} اختار مين يطلع! (20 ثانية)")).set_image(url="attachment://wheel.png")
            msg = await self.send(content=chosen.mention, embed=em, file=file, view=view)
            await view.wait()
            pick = view.result
            if pick is None or pick == "withdraw":
                out = chosen
                why = self.t("ran out of time" if pick is None else "withdrew", "خلص وقته" if pick is None else "انسحب")
            else:
                out = random.choice(others) if pick == "random" else pick
                why = self.t(f"was kicked by {chosen.mention}", f"طلع من {chosen.mention}")
            alive = [p for p in alive if p.id != out.id]
            await finish(view, msg, self.embed(f"💥 {out.mention} {why}. ({len(alive)} {self.t('left', 'باقيين')})").set_image(url="attachment://wheel.png"))
            await asyncio.sleep(4)


class DeathWheel(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        num = {p.id: i + 1 for i, p in enumerate(self.players)}
        alive = list(self.players)
        for _ in range(40):
            if len(alive) <= 1:
                break
            chosen = random.choice(alive)
            file = wheel_image([str(num[p.id]) for p in alive], alive.index(chosen))
            boxes = random.sample(["skull", "skull", "safe", "gun"], 4)
            view = self.track(PickView(self, chosen, [], extras=tuple((str(i), f"{i + 1}", "📦") for i in range(4))))
            em = self.embed(self.t(f"☠️ {chosen.mention}, pick a box! (20s)", f"☠️ {chosen.mention} اختار صندوق! (20 ثانية)")).set_image(url="attachment://wheel.png")
            msg = await self.send(content=chosen.mention, embed=em, file=file, view=view)
            await view.wait()
            if view.result is None:
                alive = [p for p in alive if p.id != chosen.id]
                await finish(view, msg, self.embed(self.t(f"⌛ {chosen.mention} ran out of time and is out.", f"⌛ {chosen.mention} خلص وقته وطلع.")))
            else:
                box = boxes[int(view.result)]
                if box == "skull":
                    alive = [p for p in alive if p.id != chosen.id]
                    await finish(view, msg, self.embed(self.t(f"💀 Skull! {chosen.mention} is out.", f"💀 جمجمة! {chosen.mention} طلع.")))
                elif box == "safe":
                    await finish(view, msg, self.embed(self.t(f"😇 Safe! {chosen.mention} survives.", f"😇 نجا! {chosen.mention} سليم.")))
                else:
                    others = [p for p in alive if p.id != chosen.id]
                    await finish(view, msg, self.embed(self.t(f"🔫 A gun! {chosen.mention} chooses who to kick.", f"🔫 مسدس! {chosen.mention} بيختار مين يطلع.")))
                    pv = self.track(PickView(self, chosen, others, {p.id: f"{num[p.id]}. {p.display_name}" for p in others}))
                    m2 = await self.send(content=chosen.mention, embed=self.embed(self.t("Who gets kicked? (20s)", "مين يطلع؟ (20 ثانية)")), view=pv)
                    await pv.wait()
                    out = pv.result if pv.result in others else random.choice(others)
                    alive = [p for p in alive if p.id != out.id]
                    await finish(pv, m2, self.embed(f"💥 {out.mention} {self.t('is out', 'طلع')}."))
            await asyncio.sleep(4)
        if len(alive) >= 1:
            await self.win(alive[:1] if len(alive) == 1 else alive)


class Chairs(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        alive = list(self.players)
        while len(alive) > 1:
            msg = await self.send(embed=self.embed(self.t("🎵 The music is playing… get ready!", "🎵 الموسيقى شغالة… جهّز حالك!")))
            await asyncio.sleep(random.uniform(3, 7))
            view = self.track(ChairsView(self, alive))
            await msg.edit(embed=self.embed(self.t("🛑 The music stopped! Grab a chair! 🪑", "🛑 وقفت الموسيقى! امسك كرسي! 🪑")), view=view)
            await view.wait()
            out = [p for p in alive if p.id not in view.seated]
            alive = [p for p in alive if p.id in view.seated]
            txt = self.t("Out: ", "طلعوا: ") + (" ".join(p.mention for p in out) or "—")
            try:
                await msg.edit(embed=self.embed(f"{txt}\n{self.t('Still in', 'باقيين')}: {len(alive)}"), view=None)
            except discord.HTTPException:
                pass
            await asyncio.sleep(3)
        if alive:
            await self.win(alive)
        else:
            await self.send(embed=self.embed(self.t("Nobody won this time.", "ما حدا فاز هالمرة."), col=0xEF4444))


class ChairsView(discord.ui.View):
    def __init__(self, game: BaseGame, alive: list):
        super().__init__(timeout=12)
        self.game = game
        self.alive_ids = {p.id for p in alive}
        self.seated: set[int] = set()
        self.trapped: set[int] = set()
        self.chairs = len(alive) - 1
        traps = 1 if len(alive) >= 4 else 0
        kinds = ["chair"] * self.chairs + ["trap"] * traps
        random.shuffle(kinds)
        for i, k in enumerate(kinds[:25]):
            b = discord.ui.Button(emoji="🪑", style=discord.ButtonStyle.secondary, row=i // 5)
            b.callback = self._mk(b, k)
            self.add_item(b)

    def _mk(self, button, kind):
        async def cb(inter: discord.Interaction):
            uid = inter.user.id
            gm = self.game
            if uid not in self.alive_ids or uid in self.seated or uid in self.trapped:
                return await inter.response.send_message(gm.t("You can't sit now.", "ما بتقدر تقعد هلأ."), ephemeral=True)
            if button.disabled:
                return await inter.response.send_message(gm.t("Taken!", "محجوز!"), ephemeral=True)
            button.disabled = True
            if kind == "trap":
                self.trapped.add(uid)
                button.emoji, button.style, button.label = "💥", discord.ButtonStyle.danger, inter.user.display_name[:20]
            else:
                self.seated.add(uid)
                button.style, button.label = discord.ButtonStyle.success, inter.user.display_name[:20]
            await inter.response.edit_message(view=self)
            if len(self.seated) >= self.chairs or len(self.seated) + len(self.trapped) >= len(self.alive_ids):
                self.stop()
        return cb


RPS = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


class ChoiceRound(discord.ui.View):
    """Every alive player picks one option once (answer is private)."""

    def __init__(self, game: BaseGame, alive: list, options: dict, timeout: float = 15):
        super().__init__(timeout=timeout)
        self.game, self.alive_ids = game, {p.id for p in alive}
        self.picks: dict[int, str] = {}
        self.all_in = asyncio.Event()
        for key, emoji in options.items():
            b = discord.ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary)
            b.callback = self._mk(key, emoji)
            self.add_item(b)

    def _mk(self, key, emoji):
        async def cb(inter: discord.Interaction):
            gm = self.game
            if inter.user.id not in self.alive_ids:
                return await inter.response.send_message(gm.t("You are not playing.", "انت مش بتلعب."), ephemeral=True)
            if inter.user.id in self.picks:
                return await inter.response.send_message(gm.t("You already picked.", "اخترت أصلاً."), ephemeral=True)
            self.picks[inter.user.id] = key
            await inter.response.send_message(f"{emoji} ✅", ephemeral=True)
            if len(self.picks) >= len(self.alive_ids):
                self.all_in.set()
        return cb


class RockPaperScissors(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        alive = list(self.players)
        for rnd in range(1, 11):
            if len(alive) <= 1:
                break
            view = self.track(ChoiceRound(self, alive, RPS))
            msg = await self.send(embed=self.embed(self.t(f"Round {rnd}: pick! (15s)", f"الجولة {rnd}: اختار! (15 ثانية)")), view=view)
            try:
                await asyncio.wait_for(view.all_in.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass
            view.stop()
            bot = random.choice(list(RPS))
            losers = [p for p in alive if view.picks.get(p.id) is None or BEATS[bot] == view.picks.get(p.id)]
            if not view.picks:
                await msg.edit(embed=self.embed(self.t("Nobody played. Game over.", "ما حدا لعب. خلصت اللعبة."), col=0xEF4444), view=None)
                return
            if len(losers) == len(alive):
                losers = [p for p in alive if view.picks.get(p.id) is None]  # everyone lost to the bot: replay the round
                if len(losers) == len(alive):
                    losers = []
            alive = [p for p in alive if p not in losers]
            lines = [f"{RPS.get(view.picks.get(p.id, ''), '⌛')} {p.mention}" for p in self.players if p in alive or p in losers]
            await msg.edit(embed=self.embed(f"PEAK: {RPS[bot]}\n\n" + "\n".join(lines) + f"\n\n{self.t('Out', 'طلعوا')}: {' '.join(p.mention for p in losers) or '—'}"), view=None)
            await asyncio.sleep(4)
        if alive:
            await self.win(alive)


class Dice(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        ps = self.players[:]
        random.shuffle(ps)
        red, blue = ps[0::2], ps[1::2]
        score = {"red": 0, "blue": 0}
        await self.send(embed=self.embed(f"🔴 {' '.join(p.mention for p in red)}\n🔵 {' '.join(p.mention for p in blue)}"))
        total = {"red": 0, "blue": 0}
        for rnd in range(1, 4):
            await asyncio.sleep(3)
            view = self.track(DiceRound(self, red, blue, rnd))
            msg = await self.send(embed=view.board(), view=view)
            try:
                await asyncio.wait_for(view.all_in.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass
            view.stop()
            r, b = view.sum("red"), view.sum("blue")
            total["red"] += r
            total["blue"] += b
            if r != b:
                score["red" if r > b else "blue"] += 1
            res = self.t("Draw", "تعادل") if r == b else ("🔴 " + self.t("Red wins the round", "الأحمر فاز بالجولة") if r > b else "🔵 " + self.t("Blue wins the round", "الأزرق فاز بالجولة"))
            try:
                await msg.edit(embed=view.board(res), view=None)
            except discord.HTTPException:
                pass
        if score["red"] == score["blue"]:
            score = total
        if score["red"] == score["blue"]:
            return await self.send(embed=self.embed(self.t("It's a draw!", "تعادل!")))
        await self.win(red if score["red"] > score["blue"] else blue)


class DiceRound(discord.ui.View):
    def __init__(self, game, red, blue, rnd):
        super().__init__(timeout=25)
        self.game, self.red, self.blue, self.rnd = game, red, blue, rnd
        self.rolls: dict[int, int] = {}
        self.all_in = asyncio.Event()
        b = discord.ui.Button(label=game.t("Roll", "ارمي"), emoji="🎲", style=discord.ButtonStyle.primary)
        b.callback = self.roll
        self.add_item(b)

    def sum(self, team):
        return sum(self.rolls.get(p.id, 0) for p in (self.red if team == "red" else self.blue))

    def board(self, result: str = "") -> discord.Embed:
        gm = self.game
        fmt = lambda ps: "\n".join(f"{p.mention}: **{self.rolls[p.id]}**" if p.id in self.rolls else f"{p.mention}: …" for p in ps)
        e = gm.embed(f"{gm.t('Round', 'الجولة')} {self.rnd}/3 — {gm.t('press Roll! (20s)', 'اضغط ارمي! (20 ثانية)')}\n\n🔴 **{self.sum('red')}**\n{fmt(self.red)}\n\n🔵 **{self.sum('blue')}**\n{fmt(self.blue)}" + (f"\n\n**{result}**" if result else ""))
        return e

    async def roll(self, inter: discord.Interaction):
        gm = self.game
        ids = {p.id for p in self.red + self.blue}
        if inter.user.id not in ids:
            return await inter.response.send_message(gm.t("You are not playing.", "انت مش بتلعب."), ephemeral=True)
        if inter.user.id in self.rolls:
            return await inter.response.send_message(gm.t("You already rolled.", "رميت أصلاً."), ephemeral=True)
        self.rolls[inter.user.id] = random.randint(1, 6)
        await inter.response.edit_message(embed=self.board(), view=self)
        if len(self.rolls) >= len(ids):
            self.all_in.set()


class Bomb(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        alive = list(self.players)
        while len(alive) > 1:
            view = self.track(BombView(self, alive, random.choice(alive)))
            msg = await self.send(content=view.holder.mention, embed=view.board(), view=view)
            await asyncio.sleep(random.uniform(10, 25))
            view.stop()
            out = view.holder
            alive = [p for p in alive if p.id != out.id]
            try:
                await msg.edit(content=None, embed=self.embed(self.t(f"💥 BOOM! {out.mention} exploded. ({len(alive)} left)", f"💥 بوووم! {out.mention} انفجر. ({len(alive)} باقيين)"), col=0xEF4444), view=None)
            except discord.HTTPException:
                pass
            await asyncio.sleep(4)
        await self.win(alive)


class BombView(discord.ui.View):
    def __init__(self, game, alive, holder):
        super().__init__(timeout=40)
        self.game, self.alive, self.holder = game, alive, holder
        b = discord.ui.Button(label=game.t("Pass the bomb", "مرّر القنبلة"), emoji="💣", style=discord.ButtonStyle.danger)
        b.callback = self.pass_it
        self.add_item(b)

    def board(self) -> discord.Embed:
        return self.game.embed(self.game.t(f"💣 The bomb is with {self.holder.mention}! Pass it fast!", f"💣 القنبلة مع {self.holder.mention}! مرّرها بسرعة!"))

    async def pass_it(self, inter: discord.Interaction):
        if inter.user.id != self.holder.id:
            return await inter.response.send_message(self.game.t("You don't have the bomb.", "القنبلة مش معك."), ephemeral=True)
        self.holder = random.choice([p for p in self.alive if p.id != self.holder.id])
        await inter.response.edit_message(content=self.holder.mention, embed=self.board(), view=self)


class Mafia(BaseGame):
    async def run(self):
        if not await self.lobby():
            return
        ps = self.players[:]
        random.shuffle(ps)
        n = len(ps)
        mafia_n = max(1, n // 4)
        roles: dict[int, str] = {}
        for p in ps[:mafia_n]:
            roles[p.id] = "mafia"
        roles[ps[mafia_n].id] = "doctor"
        if n >= 7:
            roles[ps[mafia_n + 1].id] = "detective"
        for p in ps:
            roles.setdefault(p.id, "citizen")
        self.roles = roles
        alive = list(self.players)
        info = self.t(f"🕵️ {mafia_n} mafia, 1 doctor" + (", 1 detective" if n >= 7 else "") + ". Press the button to see your role privately.", f"🕵️ {mafia_n} مافيا، 1 دكتور" + ("، 1 محقق" if n >= 7 else "") + ". اضغط الزر عشان تشوف دورك بالسر.")
        rv = self.track(RoleView(self))
        await self.send(embed=self.embed(info), view=rv)
        await asyncio.sleep(15)
        idle = 0
        for day in range(1, 16):
            night = self.track(NightView(self, alive))
            msg = await self.send(embed=self.embed(self.t("🌙 Night falls. Everyone press the button: the mafia pick a victim, the doctor protects, the detective investigates. (30s)", "🌙 نزل الليل. الكل يضغط الزر: المافيا تختار ضحية، الدكتور يحمي، المحقق يكشف. (30 ثانية)"), title=f"🌙 {self.t('Night', 'الليلة')} {day}"), view=night)
            await asyncio.sleep(30)
            night.stop()
            victim = None
            if night.kills:
                counts: dict[int, int] = {}
                for t_id in night.kills.values():
                    counts[t_id] = counts.get(t_id, 0) + 1
                top = max(counts.values())
                vid = random.choice([k for k, v in counts.items() if v == top])
                victim = next((p for p in alive if p.id == vid), None)
            if victim and victim.id != night.save:
                alive = [p for p in alive if p.id != victim.id]
                text = self.t(f"☠️ {victim.mention} was killed tonight. They were **{self.role_name(victim.id)}**.", f"☠️ {victim.mention} انقتل الليلة. كان **{self.role_name(victim.id)}**.")
            elif victim:
                text = self.t("💉 The mafia attacked, but the doctor saved the victim!", "💉 المافيا هجمت، بس الدكتور أنقذ الضحية!")
            else:
                text = self.t("😴 A quiet night, nobody died.", "😴 ليلة هادية، ما حدا مات.")
            try:
                await msg.edit(embed=self.embed(text, title=f"🌙 {self.t('Night', 'الليلة')} {day}"), view=None)
            except discord.HTTPException:
                pass
            if (w := self.winner(alive)):
                return await self.end(w)
            await asyncio.sleep(4)
            vote = self.track(VoteView(self, alive))
            alive_txt = " ".join(p.mention for p in alive)
            msg = await self.send(embed=self.embed(self.t(f"☀️ Discuss and vote who is the mafia. (45s)\n\n{alive_txt}", f"☀️ تناقشوا وصوّتوا مين المافيا. (45 ثانية)\n\n{alive_txt}"), title=f"☀️ {self.t('Day', 'النهار')} {day}"), view=vote)
            await asyncio.sleep(45)
            vote.stop()
            # Nobody acted for two whole days: everyone left, so stop instead of posting for nothing.
            idle = idle + 1 if not night.kills and not vote.votes else 0
            if idle >= 2:
                try:
                    await msg.edit(embed=self.embed(self.t("Nobody is playing anymore, the game ended.", "ما حدا عم يلعب، خلصت اللعبة.")), view=None)
                except discord.HTTPException:
                    pass
                return
            counts = {}
            for t_id in vote.votes.values():
                if t_id != "skip":
                    counts[t_id] = counts.get(t_id, 0) + 1
            out = None
            if counts:
                top = max(counts.values())
                best = [k for k, v in counts.items() if v == top]
                if len(best) == 1:
                    out = next((p for p in alive if str(p.id) == best[0]), None)
            if out:
                alive = [p for p in alive if p.id != out.id]
                text = self.t(f"⚖️ {out.mention} was voted out. They were **{self.role_name(out.id)}**.", f"⚖️ {out.mention} طلع بالتصويت. كان **{self.role_name(out.id)}**.")
            else:
                text = self.t("⚖️ No one was voted out.", "⚖️ ما حدا طلع بالتصويت.")
            try:
                await msg.edit(embed=self.embed(text, title=f"☀️ {self.t('Day', 'النهار')} {day}"), view=None)
            except discord.HTTPException:
                pass
            if (w := self.winner(alive)):
                return await self.end(w)
            await asyncio.sleep(4)
        await self.send(embed=self.embed(self.t("The game took too long and ended.", "اللعبة طوّلت وخلصت.")))

    def role_name(self, uid: int) -> str:
        r = self.roles.get(uid, "citizen")
        return {"mafia": self.t("Mafia 🔪", "مافيا 🔪"), "doctor": self.t("Doctor 💉", "دكتور 💉"), "detective": self.t("Detective 🔎", "محقق 🔎"), "citizen": self.t("Citizen 👤", "مواطن 👤")}[r]

    def winner(self, alive) -> str | None:
        m = sum(1 for p in alive if self.roles[p.id] == "mafia")
        if m == 0:
            return "town"
        if m >= len(alive) - m:
            return "mafia"
        return None

    async def end(self, w: str):
        reveal = "\n".join(f"{p.mention}: {self.role_name(p.id)}" for p in self.players)
        await self.send(embed=self.embed((self.t("🔪 The mafia won!", "🔪 المافيا فازت!") if w == "mafia" else self.t("🏙️ The town won!", "🏙️ المدينة فازت!")) + f"\n\n{reveal}"))
        await self.win([p for p in self.players if (self.roles[p.id] == "mafia") == (w == "mafia")])


class RoleView(discord.ui.View):
    def __init__(self, game: Mafia):
        super().__init__(timeout=900)
        self.game = game
        b = discord.ui.Button(label=game.t("My role", "دوري"), emoji="🎭", style=discord.ButtonStyle.primary)
        b.callback = self.show
        self.add_item(b)

    async def show(self, inter: discord.Interaction):
        gm = self.game
        if inter.user.id not in gm.roles:
            return await inter.response.send_message(gm.t("You are not playing.", "انت مش بتلعب."), ephemeral=True)
        extra = ""
        if gm.roles[inter.user.id] == "mafia":
            mates = [p.mention for p in gm.players if gm.roles[p.id] == "mafia" and p.id != inter.user.id]
            if mates:
                extra = "\n" + gm.t("Your team: ", "فريقك: ") + " ".join(mates)
        await inter.response.send_message(gm.t("Your role: ", "دورك: ") + f"**{gm.role_name(inter.user.id)}**{extra}", ephemeral=True)


class NightView(discord.ui.View):
    def __init__(self, game: Mafia, alive):
        super().__init__(timeout=40)
        self.game, self.alive = game, alive
        self.kills: dict[int, int] = {}
        self.save: int | None = None
        self.checked: set[int] = set()
        b = discord.ui.Button(label=game.t("Night action", "دورك بالليل"), emoji="🌙", style=discord.ButtonStyle.secondary)
        b.callback = self.act
        self.add_item(b)

    async def act(self, inter: discord.Interaction):
        gm = self.game
        if not any(p.id == inter.user.id for p in self.alive):
            return await inter.response.send_message(gm.t("You are out of the game.", "انت طالع من اللعبة."), ephemeral=True)
        role = gm.roles[inter.user.id]
        if role == "citizen":
            return await inter.response.send_message(gm.t("😴 You are sleeping…", "😴 انت نايم…"), ephemeral=True)
        if role == "detective" and inter.user.id in self.checked:
            return await inter.response.send_message(gm.t("You already investigated tonight.", "كشفت الليلة أصلاً."), ephemeral=True)
        if role == "mafia":
            opts = [p for p in self.alive if gm.roles[p.id] != "mafia"]
        elif role == "doctor":
            opts = list(self.alive)
        else:
            opts = [p for p in self.alive if p.id != inter.user.id]
        sel = discord.ui.Select(placeholder=gm.role_name(inter.user.id), options=[discord.SelectOption(label=p.display_name[:100], value=str(p.id)) for p in opts[:25]])
        night = self

        async def picked(i2: discord.Interaction):
            if night.is_finished():
                return await i2.response.edit_message(content=gm.t("Too late, the night is over.", "متأخر، خلص الليل."), view=None)
            tid = int(sel.values[0])
            name = next((p.display_name for p in opts if p.id == tid), "?")
            if role == "mafia":
                night.kills[i2.user.id] = tid
                txt = gm.t(f"🔪 Target: {name}", f"🔪 الضحية: {name}")
            elif role == "doctor":
                night.save = tid
                txt = gm.t(f"💉 You protect {name}", f"💉 بتحمي {name}")
            else:
                night.checked.add(i2.user.id)
                is_m = gm.roles.get(tid) == "mafia"
                txt = gm.t(f"🔎 {name} is {'MAFIA 🔪' if is_m else 'not mafia ✅'}", f"🔎 {name} {'مافيا 🔪' if is_m else 'مش مافيا ✅'}")
            await i2.response.edit_message(content=txt, view=None)

        sel.callback = picked
        v = discord.ui.View(timeout=35)
        v.add_item(sel)
        await inter.response.send_message(view=v, ephemeral=True)


class VoteView(discord.ui.View):
    def __init__(self, game: Mafia, alive):
        super().__init__(timeout=50)
        self.game, self.alive = game, alive
        self.votes: dict[int, str] = {}
        opts = [discord.SelectOption(label=p.display_name[:100], value=str(p.id)) for p in alive[:24]]
        opts.append(discord.SelectOption(label=game.t("Skip", "تخطي"), value="skip", emoji="⏭️"))
        self.sel = discord.ui.Select(placeholder=game.t("Vote", "صوّت"), options=opts)
        self.sel.callback = self.vote
        self.add_item(self.sel)

    async def vote(self, inter: discord.Interaction):
        gm = self.game
        if not any(p.id == inter.user.id for p in self.alive):
            return await inter.response.send_message(gm.t("Only alive players can vote.", "بس اللاعبين الأحياء بيصوّتوا."), ephemeral=True)
        v = self.sel.values[0]
        self.votes[inter.user.id] = v
        name = gm.t("skip", "تخطي") if v == "skip" else next((p.display_name for p in self.alive if str(p.id) == v), "?")
        await inter.response.send_message(gm.t(f"🗳️ Your vote: {name}", f"🗳️ صوتك: {name}"), ephemeral=True)


XO_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


class XO(BaseGame):
    async def run(self):
        hot = self.gid == "hotxo"
        inv = self.track(InviteView(self))
        who = self.opponent.mention if self.opponent else self.t("anyone", "أي حدا")
        msg = await self.send(content=self.opponent.mention if self.opponent else None, embed=self.embed(self.t(f"{self.starter.mention} challenges {who}! (30s)", f"{self.starter.mention} بيتحدى {who}! (30 ثانية)") + ("\n" + self.t("Hot: you keep only 3 marks, the oldest one disappears.", "نار: كل لاعب إله 3 علامات بس، والأقدم بتختفي.") if hot else "")), view=inv)
        await inv.wait()
        if not inv.accepted:
            return await finish(inv, msg, self.embed(self.t("Nobody accepted the challenge.", "ما حدا قبل التحدي."), col=0xEF4444))
        self.players = [self.starter, inv.accepted]
        random.shuffle(self.players)
        board = self.track(XOBoard(self, hot))
        await finish(inv, msg, self.embed(self.t("Challenge accepted!", "انقبل التحدي!")))
        bmsg = await self.send(content=board.turn.mention, embed=board.status(), view=board)
        await board.wait()
        if board.result is None:  # the player whose turn it was did not play in time
            loser = board.turn
            winner = next(p for p in self.players if p.id != loser.id)
            try:
                await bmsg.edit(content=None, embed=self.embed(self.t(f"⌛ {loser.mention} ran out of time.", f"⌛ {loser.mention} خلص وقته.")), view=None)
            except discord.HTTPException:
                pass
            return await self.win([winner])
        if board.result == "draw":
            return await self.send(embed=self.embed(self.t("🤝 It's a draw!", "🤝 تعادل!")))
        await self.win([board.result])


class InviteView(discord.ui.View):
    def __init__(self, game: BaseGame):
        super().__init__(timeout=30)
        self.game = game
        self.accepted = None
        self.inter = None
        b = discord.ui.Button(label=game.t("Accept", "قبول"), emoji="✅", style=discord.ButtonStyle.success)
        b.callback = self.accept
        self.add_item(b)

    async def accept(self, inter: discord.Interaction):
        gm = self.game
        if inter.user.id == gm.starter.id or inter.user.bot or (gm.opponent and inter.user.id != gm.opponent.id):
            return await inter.response.send_message(gm.t("This challenge is not for you.", "التحدي مش إلك."), ephemeral=True)
        self.accepted, self.inter = inter.user, inter
        self.stop()


class XOBoard(discord.ui.View):
    def __init__(self, game: XO, hot: bool):
        super().__init__(timeout=60)  # 60s per move: the timer restarts on every click
        self.game, self.hot = game, hot
        self.cells: list[int | None] = [None] * 9
        self.marks = {game.players[0].id: "❌", game.players[1].id: "⭕"}
        self.history: dict[int, list[int]] = {p.id: [] for p in game.players}
        self.turn = game.players[0]
        self.moves = 0
        self.result = None
        for i in range(9):
            b = discord.ui.Button(label="\u200b", style=discord.ButtonStyle.secondary, row=i // 3)
            b.callback = self._mk(i)
            self.add_item(b)

    def status(self, text: str = "") -> discord.Embed:
        gm = self.game
        a, b = gm.players
        return gm.embed(f"❌ {a.mention}  vs  ⭕ {b.mention}\n\n" + (text or gm.t(f"Turn: {self.marks[self.turn.id]} {self.turn.mention}", f"الدور: {self.marks[self.turn.id]} {self.turn.mention}")))

    def redraw(self):
        for i, b in enumerate(self.children):
            owner = self.cells[i]
            b.label = "\u200b" if owner is None else None
            b.emoji = None if owner is None else self.marks[owner]
            b.style = discord.ButtonStyle.secondary if owner is None else (discord.ButtonStyle.danger if self.marks[owner] == "❌" else discord.ButtonStyle.primary)
            b.disabled = owner is not None

    def _mk(self, i):
        async def cb(inter: discord.Interaction):
            gm = self.game
            if inter.user.id != self.turn.id:
                return await inter.response.send_message(gm.t("It's not your turn.", "مش دورك."), ephemeral=True)
            if self.cells[i] is not None:
                return await inter.response.send_message(gm.t("That spot is taken.", "المكان محجوز."), ephemeral=True)
            uid = self.turn.id
            if self.hot and len(self.history[uid]) >= 3:
                self.cells[self.history[uid].pop(0)] = None
            self.cells[i] = uid
            self.history[uid].append(i)
            self.moves += 1
            won = any(self.cells[x] == uid and self.cells[y] == uid and self.cells[z] == uid for x, y, z in XO_LINES)
            self.redraw()
            if won:
                self.result = self.turn
                for b in self.children:
                    b.disabled = True
                self.stop()
                return await inter.response.edit_message(content=None, embed=self.status(f"🏆 {self.turn.mention}"), view=self)
            if (not self.hot and all(c is not None for c in self.cells)) or self.moves >= 40:
                self.result = "draw"
                self.stop()
                return await inter.response.edit_message(content=None, embed=self.status("🤝"), view=None)
            self.turn = next(p for p in gm.players if p.id != uid)
            await inter.response.edit_message(content=self.turn.mention, embed=self.status(), view=self)
        return cb


# ---- mini games: first right answer in the chat wins
WORDS_AR = [
    "سيارة", "مدرسة", "كمبيوتر", "برتقالة", "طيارة", "مستشفى", "ديسكورد", "كرة القدم", "شوكولاتة", "قهوة", "مفتاح", "جبل", "بحر",
    "صحراء", "نجمة", "قمر", "شمس", "مكتبة", "حديقة", "تفاحة", "موز", "فراولة", "بطيخ", "زرافة", "فيل", "أسد", "نمر", "حصان",
    "دولفين", "قلم", "دفتر", "شباك", "باب", "كرسي", "طاولة", "تلفزيون", "موبايل", "سماعة", "لابتوب", "بيتزا", "برجر", "شاورما",
    "فلافل", "منسف", "كنافة", "مطار", "قطار", "سفينة", "دراجة", "صاروخ", "كوكب", "مجرة", "غيمة", "مطر", "ثلج", "رعد", "قوس قزح",
    "صديق", "عائلة", "مدينة", "قرية", "ملعب", "بطولة", "جائزة", "ذهب", "فضة", "الماس", "كنز", "قلعة", "ملك", "فارس",
]
WORDS_EN = [
    "discord", "keyboard", "elephant", "pineapple", "computer", "airplane", "hospital", "chocolate", "mountain", "football",
    "rainbow", "thunder", "galaxy", "planet", "rocket", "castle", "treasure", "diamond", "giraffe", "dolphin", "library",
    "window", "pizza", "burger", "coffee", "school", "garden", "banana", "orange", "strawberry", "headphones", "laptop",
    "bicycle", "train", "island", "desert", "volcano", "penguin", "kangaroo", "butterfly",
]
FLAGS = [
    ("🇯🇴", ["الاردن", "jordan"]), ("🇸🇦", ["السعودية", "saudi arabia", "saudi"]), ("🇪🇬", ["مصر", "egypt"]), ("🇵🇸", ["فلسطين", "palestine"]),
    ("🇮🇶", ["العراق", "iraq"]), ("🇸🇾", ["سوريا", "سورية", "syria"]), ("🇱🇧", ["لبنان", "lebanon"]), ("🇦🇪", ["الامارات", "uae", "emirates"]),
    ("🇰🇼", ["الكويت", "kuwait"]), ("🇶🇦", ["قطر", "qatar"]), ("🇧🇭", ["البحرين", "bahrain"]), ("🇴🇲", ["عمان", "oman"]),
    ("🇾🇪", ["اليمن", "yemen"]), ("🇲🇦", ["المغرب", "morocco"]), ("🇩🇿", ["الجزائر", "algeria"]), ("🇹🇳", ["تونس", "tunisia"]),
    ("🇱🇾", ["ليبيا", "libya"]), ("🇸🇩", ["السودان", "sudan"]), ("🇹🇷", ["تركيا", "turkey"]), ("🇫🇷", ["فرنسا", "france"]),
    ("🇩🇪", ["المانيا", "germany"]), ("🇮🇹", ["ايطاليا", "italy"]), ("🇪🇸", ["اسبانيا", "spain"]), ("🇬🇧", ["بريطانيا", "uk", "united kingdom", "england"]),
    ("🇺🇸", ["امريكا", "usa", "united states", "america"]), ("🇨🇦", ["كندا", "canada"]), ("🇧🇷", ["البرازيل", "brazil"]), ("🇦🇷", ["الارجنتين", "argentina"]),
    ("🇯🇵", ["اليابان", "japan"]), ("🇨🇳", ["الصين", "china"]), ("🇰🇷", ["كوريا", "كوريا الجنوبية", "korea", "south korea"]), ("🇮🇳", ["الهند", "india"]),
    ("🇷🇺", ["روسيا", "russia"]), ("🇵🇹", ["البرتغال", "portugal"]), ("🇳🇱", ["هولندا", "netherlands"]), ("🇧🇪", ["بلجيكا", "belgium"]),
    ("🇸🇪", ["السويد", "sweden"]), ("🇳🇴", ["النرويج", "norway"]), ("🇲🇽", ["المكسيك", "mexico"]), ("🇦🇺", ["استراليا", "australia"]),
    ("🇬🇷", ["اليونان", "greece"]), ("🇮🇷", ["ايران", "iran"]), ("🇵🇰", ["باكستان", "pakistan"]), ("🇮🇩", ["اندونيسيا", "indonesia"]),
    ("🇲🇾", ["ماليزيا", "malaysia"]), ("🇳🇬", ["نيجيريا", "nigeria"]), ("🇿🇦", ["جنوب افريقيا", "south africa"]), ("🇨🇭", ["سويسرا", "switzerland"]),
]
CAPITALS = [
    (("الاردن", "Jordan"), ["عمان", "amman"]), (("السعودية", "Saudi Arabia"), ["الرياض", "riyadh"]), (("مصر", "Egypt"), ["القاهرة", "cairo"]),
    (("العراق", "Iraq"), ["بغداد", "baghdad"]), (("سوريا", "Syria"), ["دمشق", "damascus"]), (("لبنان", "Lebanon"), ["بيروت", "beirut"]),
    (("الامارات", "UAE"), ["ابوظبي", "ابو ظبي", "abu dhabi"]), (("الكويت", "Kuwait"), ["الكويت", "kuwait city", "kuwait"]), (("قطر", "Qatar"), ["الدوحة", "doha"]),
    (("البحرين", "Bahrain"), ["المنامة", "manama"]), (("عمان", "Oman"), ["مسقط", "muscat"]), (("اليمن", "Yemen"), ["صنعاء", "sanaa"]),
    (("المغرب", "Morocco"), ["الرباط", "rabat"]), (("الجزائر", "Algeria"), ["الجزائر", "algiers"]), (("تونس", "Tunisia"), ["تونس", "tunis"]),
    (("ليبيا", "Libya"), ["طرابلس", "tripoli"]), (("السودان", "Sudan"), ["الخرطوم", "khartoum"]), (("تركيا", "Turkey"), ["انقرة", "ankara"]),
    (("فرنسا", "France"), ["باريس", "paris"]), (("المانيا", "Germany"), ["برلين", "berlin"]), (("ايطاليا", "Italy"), ["روما", "rome"]),
    (("اسبانيا", "Spain"), ["مدريد", "madrid"]), (("بريطانيا", "United Kingdom"), ["لندن", "london"]), (("امريكا", "USA"), ["واشنطن", "washington"]),
    (("كندا", "Canada"), ["اوتاوا", "ottawa"]), (("البرازيل", "Brazil"), ["برازيليا", "brasilia"]), (("الارجنتين", "Argentina"), ["بوينس ايرس", "buenos aires"]),
    (("اليابان", "Japan"), ["طوكيو", "tokyo"]), (("الصين", "China"), ["بكين", "beijing"]), (("الهند", "India"), ["نيودلهي", "نيو دلهي", "new delhi"]),
    (("روسيا", "Russia"), ["موسكو", "moscow"]), (("البرتغال", "Portugal"), ["لشبونة", "lisbon"]), (("هولندا", "Netherlands"), ["امستردام", "amsterdam"]),
    (("اليونان", "Greece"), ["اثينا", "athens"]), (("ايران", "Iran"), ["طهران", "tehran"]), (("استراليا", "Australia"), ["كانبرا", "canberra"]),
    (("كوريا الجنوبية", "South Korea"), ["سيول", "seoul"]), (("السويد", "Sweden"), ["ستوكهولم", "stockholm"]), (("النرويج", "Norway"), ["اوسلو", "oslo"]),
    (("المكسيك", "Mexico"), ["مكسيكو", "مكسيكو سيتي", "mexico city"]), (("سويسرا", "Switzerland"), ["برن", "bern"]),
]
EMOJI_POOL = ["🍎", "🍌", "🍇", "🍉", "🍓", "🍒", "🥝", "🍍", "🥥", "🍑"]


def make_question(gid: str, s: dict) -> tuple[str, list[str], bool]:
    """Returns (text shown, accepted answers, loose name match)."""
    ar = L(s, "en", "ar") == "ar"
    words = WORDS_AR if ar else WORDS_EN
    if gid == "fast":
        w = random.choice(words)
        # Invisible characters between the letters: a copied answer contains them and is ignored.
        return L(s, "Type this word as fast as you can:", "اكتب هالكلمة بأسرع وقت:") + f"\n# {chr(8203).join(w)}", [w], False
    if gid == "reverse":
        w = random.choice([x for x in words if " " not in x])
        return L(s, "Write this word backwards:", "اكتب هالكلمة بالعكس:") + f"\n# {chr(8203).join(w)}", [w[::-1]], False
    if gid == "split":
        w = random.choice([x for x in words if " " not in x])
        return L(s, "Split this word into letters (with spaces):", "فكك هالكلمة لحروف (بينهم مسافات):") + f"\n# {chr(8203).join(w)}", [" ".join(w)], False
    if gid == "merge":
        w = random.choice([x for x in words if " " not in x])
        return L(s, "Join these letters into a word:", "ركّب هالحروف لكلمة:") + f"\n# {(' ' + chr(8203)).join(w)}", [w], False
    if gid == "flag":
        flag, names = random.choice(FLAGS)
        return L(s, "Which country is this flag?", "هاد علم أي دولة؟") + f"\n# {flag}", names, True
    if gid == "capital":
        (c_ar, c_en), caps = random.choice(CAPITALS)
        return L(s, f"What is the capital of **{c_en}**?", f"شو عاصمة **{c_ar}**؟"), caps, True
    if gid == "math":
        op = random.choice(["+", "-", "×"])
        a, b = (random.randint(10, 99), random.randint(10, 99)) if op != "×" else (random.randint(2, 15), random.randint(2, 12))
        res = a + b if op == "+" else a - b if op == "-" else a * b
        return L(s, "Solve:", "احسب:") + f"\n# {a} {op} {b}", [str(res)], False
    if gid == "sort":
        nums = random.sample(range(1, 100), 5)
        return L(s, "Sort from smallest to biggest (with spaces):", "رتب من الأصغر للأكبر (بينهم مسافات):") + f"\n# {'  '.join(map(str, nums))}", [" ".join(map(str, sorted(nums)))], False
    # emoji: count one emoji among others
    target = random.choice(EMOJI_POOL)
    n = random.randint(4, 12)
    others = [random.choice([e for e in EMOJI_POOL if e != target]) for _ in range(random.randint(6, 14))]
    row = [target] * n + others
    random.shuffle(row)
    return L(s, f"How many {target} are there?", f"كم {target} في؟") + "\n" + "".join(row), [str(n)], False


class MiniGame(BaseGame):
    async def run(self):
        text, answers, loose = make_question(self.gid, self.s)
        key = canon if loose else norm
        ok = {key(a) for a in answers}
        await self.send(embed=self.embed(f"{text}\n\n⏳ 20s"))
        start = time.monotonic()

        def check(m: discord.Message) -> bool:
            return m.channel.id == self.channel.id and not m.author.bot and not ZW_RE.search(m.content) and key(m.content) in ok

        try:
            m = await client.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            return await self.send(embed=self.embed(self.t(f"⌛ Time's up! The answer was **{answers[0]}**", f"⌛ خلص الوقت! الجواب كان **{answers[0]}**"), col=0xEF4444))
        await self.win([m.author], f"⚡ {time.monotonic() - start:.2f}s")


GAME_CLASSES = {
    "roulette": Roulette, "mafia": Mafia, "chairs": Chairs, "rps": RockPaperScissors, "dice": Dice, "deathwheel": DeathWheel,
    "bomb": Bomb, "xo": XO, "hotxo": XO, **{k: MiniGame for k, v in GAME_INFO.items() if v[3] == "mini"},
}


async def start_game(ch, starter: discord.Member, gid: str, s: dict, opponent: discord.Member | None = None) -> str | None:
    """Starts a game in `ch`. Returns a reason when it cannot start."""
    gs = games_cfg(s)
    if not gs.get("enabled"):
        return L(s, "Games are turned off in this server.", "الألعاب مطفية بهالسيرفر.")
    if gid not in GAME_INFO or (gs.get("list") or {}).get(gid) is False:
        return L(s, "This game is turned off.", "هاللعبة مطفية.")
    if not isinstance(ch, discord.TextChannel) and not isinstance(ch, discord.Thread):
        return L(s, "Games work in text channels only.", "الألعاب بس بالرومات الكتابية.")
    if not games_allowed(s, ch):
        return L(s, "Games are not allowed in this channel.", "الألعاب مش مسموحة بهالروم.")
    if not can_manage_games(starter, s):
        return L(s, "You are not allowed to start games.", "ما عندك صلاحية تبدأ ألعاب.")
    if ch.id in RUNNING:
        return L(s, "A game is already running in this channel.", "في لعبة شغالة بهالروم.")
    if gid in SERVER_GAMES and sum(1 for x in RUNNING.values() if x.guild_id == ch.guild.id and x.gid in SERVER_GAMES) >= 3:
        return L(s, "3 big games are already running in this server. Wait for one to finish.", "في 3 ألعاب كبيرة شغالة بالسيرفر. استنى وحدة تخلص.")
    if len(RUNNING) >= 60:
        return L(s, "PEAK is busy right now, try again in a minute.", "البوت مشغول هلأ، جرب كمان دقيقة.")
    if opponent is not None and (opponent.bot or opponent.id == starter.id):
        opponent = None
    game = GAME_CLASSES[gid](ch, starter, s, gid, opponent)
    RUNNING[ch.id] = game
    game.task = asyncio.create_task(game.safe_run())
    return None


def stop_game(ch, member: discord.Member, s: dict) -> str:
    game = RUNNING.get(ch.id)
    if not game:
        return L(s, "No game is running here.", "ما في لعبة شغالة هون.")
    if member.id != game.starter.id and not (is_mod(member) or (games_cfg(s).get("managerRoles") and can_manage_games(member, s))):
        return L(s, "Only the one who started the game or a moderator can stop it.", "بس اللي بلّش اللعبة أو المشرف بقدر يوقفها.")
    RUNNING.pop(ch.id, None)
    if game.task:
        game.task.cancel()
    return L(s, "⏹️ The game was stopped.", "⏹️ انوقفت اللعبة.")


async def handle_games_message(m: discord.Message, s: dict) -> bool:
    gs = games_cfg(s)
    if not gs.get("enabled"):
        return False
    prefix = (gs.get("prefix") or "-").strip() or "-"
    if not m.content.startswith(prefix):
        return False
    parts = m.content[len(prefix):].split()
    if not parts:
        return False
    word = norm(parts[0])
    is_stop = word in STOP_WORDS
    gid = GAME_WORDS.get(word) or GAME_WORDS.get(norm("".join(parts[:3])))
    if not is_stop and not gid:
        return False
    if not games_allowed(s, m.channel):
        return True
    key = (m.guild.id, m.author.id)
    if time.monotonic() - _game_spam.get(key, 0) < 4:
        return True
    _game_spam[key] = time.monotonic()
    try:
        if is_stop:
            await m.channel.send(embed=discord.Embed(description=stop_game(m.channel, m.author, s), color=color(s)))
            return True
        opponent = next((x for x in m.mentions if isinstance(x, discord.Member)), None)
        err = await start_game(m.channel, m.author, gid, s, opponent)
        if err:
            await m.channel.send(embed=discord.Embed(description=f"❌ {err}", color=0xEF4444), delete_after=8)
    except discord.HTTPException:
        pass
    return True


GAME_CHOICES = [app_commands.Choice(name=f"{v[1]} — {v[2]}"[:100], value=k) for k, v in GAME_INFO.items()][:25]


@tree.command(name="play", description="Start a PEAK game in this channel")
@app_commands.guild_only()
@app_commands.describe(game="Which game", opponent="XO: who you want to challenge")
@app_commands.choices(game=GAME_CHOICES)
async def slash_play(inter: discord.Interaction, game: app_commands.Choice[str], opponent: discord.Member | None = None):
    s = S(inter.guild)
    err = await start_game(inter.channel, inter.user, game.value, s, opponent)
    await inter.response.send_message(f"❌ {err}" if err else f"✅ {gname(s, game.value)}", ephemeral=True)


@tree.command(name="stop", description="Stop the PEAK game running in this channel")
@app_commands.guild_only()
async def slash_stop(inter: discord.Interaction):
    s = S(inter.guild)
    await inter.response.send_message(stop_game(inter.channel, inter.user, s))


# ------------------------------------------------------------------ emoji helpers
def safe_emoji(value: str | None, default: str | None = None) -> discord.PartialEmoji | None:
    """'<:name:id>', '<a:name:id>' or a normal emoji -> PartialEmoji. Plain words are refused (Discord would reject them)."""
    v = (value or "").strip()
    if v:
        try:
            pe = discord.PartialEmoji.from_str(v)
            if pe.id or any(ord(c) > 0x2000 for c in v):
                return pe
        except Exception:  # noqa: BLE001
            pass
    return safe_emoji(default) if default else None


def emoji_key(e) -> str:
    pe = e if isinstance(e, discord.PartialEmoji) else safe_emoji(str(e))
    if not pe:
        return ""
    return f"id:{pe.id}" if pe.id else "u:" + (pe.name or "").replace("\ufe0f", "")


# ------------------------------------------------------------------ punishment DMs
MOD_DM_DEFAULTS = {
    "warn": "⚠️ You got warned in **{server}**.",
    "timeout": "🔇 You got timed out in **{server}** for {duration}.",
    "kick": "👢 You got kicked from **{server}**.",
    "ban": "🔨 You got banned from **{server}**.",
}
MOD_DM_COLORS = {"warn": 0xF59E0B, "timeout": 0xF59E0B, "kick": 0xF97316, "ban": 0xEF4444}


def mod_dm_embed(guild, s: dict, kind: str, moderator, reason: str, minutes: int | None = None) -> discord.Embed | None:
    md = g(s, "modDm", {}) or {}
    if not md.get("enabled") or g(md, f"{kind}.enabled", True) is False:
        return None
    dur = "-"
    if minutes:
        dur = f"{minutes // 60}h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes}m"
    text = (g(md, f"{kind}.message", "") or MOD_DM_DEFAULTS[kind])
    text = text.replace("{server}", guild.name).replace("{reason}", reason or "-").replace("{moderator}", str(moderator)).replace("{duration}", dur)
    desc = text[:3000] + f"\n\n**{L(s, 'Reason', 'السبب')}:** {(reason or '-')[:900]}"
    if md.get("showModerator"):
        desc += f"\n**{L(s, 'By', 'من')}:** {moderator}"
    em = discord.Embed(description=desc, color=MOD_DM_COLORS.get(kind, 0xF59E0B), timestamp=datetime.now(timezone.utc))
    em.set_author(name=guild.name, icon_url=guild.icon.url if getattr(guild, "icon", None) else None)
    return em


async def dm_punished(target, guild, s: dict, kind: str, moderator, reason: str, minutes: int | None = None):
    """Opt-in private message to the punished member (sent before a kick/ban so it can still arrive)."""
    if getattr(target, "bot", False):
        return
    em = mod_dm_embed(guild, s, kind, moderator, reason, minutes)
    if not em:
        return
    try:
        await asyncio.wait_for(target.send(embed=em), timeout=5)
    except (discord.HTTPException, asyncio.TimeoutError):
        pass  # DMs closed: the punishment still goes ahead


# ------------------------------------------------------------------ auto emoji reactions
_react_pending: dict[int, int] = defaultdict(int)


def auto_react_emojis(m, s: dict) -> list[str]:
    out: list[str] = []
    has_media = bool(getattr(m, "attachments", None)) or bool(getattr(m, "embeds", None) and any(e.image or e.thumbnail for e in m.embeds))
    for r in g(s, "autoReact.rules", []) or []:
        if str(m.channel.id) not in (r.get("channels") or []):
            continue
        if r.get("onlyImages") and not has_media:
            continue
        for e in (r.get("emojis") or [])[:5]:
            if e and e not in out:
                out.append(e)
    return out[:10]


def start_auto_react(m: discord.Message, s: dict):
    emojis = auto_react_emojis(m, s)
    if not emojis:
        return
    if _react_pending[m.channel.id] >= 5:  # a flood of messages: skip instead of queueing hundreds of reactions
        return
    asyncio.create_task(_auto_react(m, emojis))


async def _auto_react(m: discord.Message, emojis: list[str]):
    _react_pending[m.channel.id] += 1
    try:
        for e in emojis:
            pe = safe_emoji(e)
            if not pe:
                continue
            try:
                await m.add_reaction(pe)
            except discord.NotFound:
                return  # message deleted
            except discord.HTTPException:
                pass  # unknown emoji / no permission: try the next one
            await asyncio.sleep(0.35)
    finally:
        _react_pending[m.channel.id] -= 1


# ------------------------------------------------------------------ auto reply
_reply_last: dict[tuple, float] = {}


def find_auto_reply(s: dict, channel_id: int, content: str) -> dict | None:
    text = norm(content)
    if not text:
        return None
    for r in g(s, "autoReply.replies", []) or []:
        if r.get("enabled") is False or not (r.get("response") or "").strip():
            continue
        chans = r.get("channels") or []
        if chans and str(channel_id) not in chans:
            continue
        mode = r.get("match", "exact")
        for t in r.get("triggers") or []:
            nt = norm(t)
            if not nt:
                continue
            if (mode == "exact" and text == nt) or (mode == "startsWith" and text.startswith(nt)) or (mode == "contains" and f" {nt} " in f" {text} "):
                return r
    return None


async def auto_reply(m: discord.Message, s: dict):
    r = find_auto_reply(s, m.channel.id, m.content)
    if not r:
        return
    key = (m.channel.id, r.get("id"))
    cd = max(2, int(g(s, "autoReply.cooldownSeconds", 3) or 3))
    if time.monotonic() - _reply_last.get(key, 0) < cd:
        return
    _reply_last[key] = time.monotonic()
    text = fill(r["response"], m.author, m.guild)[:2000]
    kwargs = {"embed": discord.Embed(description=text[:4000], color=color(s))} if r.get("asEmbed") else {"content": text}
    try:
        if r.get("asReply", True):
            await m.reply(mention_author=False, **kwargs)
        else:
            await m.channel.send(**kwargs)
    except discord.HTTPException:
        pass


# ------------------------------------------------------------------ -games / -اوامر
GAMES_LIST_WORDS = {"games", "game", "العاب", "الالعاب", "لعبات"}
BANK_HELP_WORDS = {"اوامر", "الاوامر", "commands", "cmds", "help"}
BANK_HELP = [
    ("رصيد / balance", "Wallet and bank balance", "رصيد المحفظة والبنك"),
    ("يومي / daily", "Daily reward", "الهدية اليومية"),
    ("راتب / work", "Work for coins", "اشتغل وخذ راتب"),
    ("تحويل / transfer @user 100", "Send coins", "حوّل لشخص"),
    ("ايداع / deposit 100", "Wallet → bank (safe from robbers)", "من المحفظة للبنك (محمي من السرقة)"),
    ("سحب / withdraw 100", "Bank → wallet", "من البنك للمحفظة"),
    ("نهب / rob @user", "Try to rob a wallet", "حاول تسرق محفظة"),
    ("قمار / bet 100", "Double or nothing", "يا بتضاعف يا بتخسر"),
    ("سلوت / slots 100", "Slot machine", "آلة الحظ"),
    ("وجه / coinflip 100", "Heads or tails", "ملك ولا كتابة"),
    ("الاغنى / rich", "Richest members", "أغنى الأعضاء"),
    ("بنك / bank", "Bank buttons menu", "قائمة أزرار البنك"),
    ("اعطاء / give @user 100", "Admins: add or remove coins (use -100)", "للإدارة: إضافة أو سحب (استخدم -100)"),
]


def games_list_embed(s: dict) -> discord.Embed:
    gs = games_cfg(s)
    p = (gs.get("prefix") or "-").strip() or "-"
    on = [k for k in GAME_INFO if (gs.get("list") or {}).get(k) is not False]
    em = discord.Embed(title=f"🎮 {L(s, 'PEAK Games', 'ألعاب PEAK')}", color=color(s))
    for kind, en, ar in (("server", "Server games (everyone joins)", "ألعاب السيرفر (الكل يشارك)"), ("duel", "1 vs 1", "واحد ضد واحد"), ("mini", "Quick games", "ألعاب سريعة")):
        lines = []
        for k in on:
            e, gen, gar, kk, _ = GAME_INFO[k]
            if kk != kind:
                continue
            word = gar.split()[0]
            lines.append(f"{e} **{L(s, gen, gar)}** — `{p}{word}`" + (" `@user`" if kind == "duel" else ""))
        if lines:
            em.add_field(name=L(s, en, ar), value="\n".join(lines)[:1024], inline=False)
    em.description = L(s, f"Type the command or pick a game from the menu. Stop a game with `{p}stop`.", f"اكتب الأمر أو اختار لعبة من القائمة. لإيقاف اللعبة `{p}ايقاف`.")
    img = str(gs.get("listImage") or "")
    if img.startswith("http"):
        em.set_image(url=img)
    return em


def games_list_view(s: dict) -> discord.ui.View | None:
    gs = games_cfg(s)
    on = [k for k in GAME_INFO if (gs.get("list") or {}).get(k) is not False][:25]
    if not on:
        return None
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Select(
        custom_id="peak:games:panel",
        placeholder=L(s, "Choose a game", "اختار لعبة"),
        options=[discord.SelectOption(label=L(s, GAME_INFO[k][1], GAME_INFO[k][2])[:100], value=k, emoji=GAME_INFO[k][0]) for k in on],
    ))
    return v


def bank_help_embed(s: dict) -> discord.Embed:
    p = g(s, "general.prefix", "!") or "!"
    b = bank_cfg(s)
    em = discord.Embed(title=f"🏦 {L(s, 'Bank commands', 'أوامر البنك')}", color=color(s))
    em.description = "\n".join(f"`{p}{c}` — {L(s, en, ar)}" for c, en, ar in BANK_HELP)[:4000]
    em.set_footer(text=L(s, f"Currency: {b.get('currencyName', 'Coins')} • Slash: /balance /daily /work /transfer /bank /rich",
                         f"العملة: {b.get('currencyName', 'Coins')} • سلاش: /balance /daily /work /transfer /bank /rich"))
    return em


async def handle_help_message(m: discord.Message, s: dict) -> bool:
    """-games sends the games list, -اوامر sends the bank commands. Uses the games prefix."""
    gs = games_cfg(s)
    prefix = (gs.get("prefix") or "-").strip() or "-"
    if not m.content.startswith(prefix):
        return False
    parts = m.content[len(prefix):].split()
    if len(parts) != 1:
        return False
    word = norm(parts[0])
    is_games = word in GAMES_LIST_WORDS and gs.get("enabled")
    is_bank = word in BANK_HELP_WORDS and bank_cfg(s).get("enabled")
    if not (is_games or is_bank):
        return False
    key = (m.guild.id, m.author.id, "help")
    if time.monotonic() - _game_spam.get(key, 0) < 5:
        return True
    _game_spam[key] = time.monotonic()
    try:
        if is_games:
            view = games_list_view(s)
            await m.channel.send(embed=games_list_embed(s), **({"view": view} if view else {}))
        else:
            await m.channel.send(embed=bank_help_embed(s))
    except discord.HTTPException:
        pass
    return True


# ------------------------------------------------------------------ emoji roles
def rr_panels(s: dict) -> list:
    return (g(s, "reactionRoles.panels", []) or []) if g(s, "reactionRoles.enabled") else []


def rr_find(s: dict, message_id: int):
    return next((p for p in rr_panels(s) if p.get("messageId") == str(message_id) and p.get("mode") != "buttons"), None)


def rr_role(guild: discord.Guild, rid) -> discord.Role | None:
    try:
        role = guild.get_role(int(rid)) if rid else None
    except (TypeError, ValueError):
        return None
    if not role or role.managed or role.is_default() or role >= guild.me.top_role:
        return None
    return role


async def rr_apply(member: discord.Member, panel: dict, item: dict, add: bool) -> discord.Role | None:
    guild = member.guild
    role = rr_role(guild, item.get("roleId"))
    if not role:
        return None
    if add:
        if panel.get("unique"):
            others = [r for it in panel.get("items", []) if it is not item and (r := rr_role(guild, it.get("roleId"))) and r in member.roles and r != role]
            if others:
                await member.remove_roles(*others, reason="PEAK emoji roles (one role only)")
        if role not in member.roles:
            await member.add_roles(role, reason="PEAK emoji roles")
    elif role in member.roles:
        await member.remove_roles(role, reason="PEAK emoji roles")
    return role


@client.event
async def on_raw_reaction_add(p: discord.RawReactionActionEvent):
    if not p.guild_id or (client.user and p.user_id == client.user.id):
        return
    guild = client.get_guild(p.guild_id)
    if not guild:
        return
    s = S(guild)
    panel = rr_find(s, p.message_id)
    if not panel:
        return
    key = emoji_key(p.emoji)
    item = next((it for it in panel.get("items", []) if it.get("roleId") and emoji_key(it.get("emoji", "")) == key), None)
    member = p.member or guild.get_member(p.user_id)
    if not item or not member or member.bot:
        return
    try:
        await rr_apply(member, panel, item, True)
        if panel.get("unique"):
            # Take the member's other reactions off this message so the picture matches their role.
            ch = guild.get_channel_or_thread(p.channel_id)
            msg = discord.PartialMessage(channel=ch, id=p.message_id) if isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel)) else None
            for it in panel.get("items", []):
                if msg and it is not item and it.get("emoji"):
                    pe = safe_emoji(it["emoji"])
                    if pe:
                        try:
                            await msg.remove_reaction(pe, member)
                        except discord.HTTPException:
                            pass
                        await asyncio.sleep(0.35)
    except discord.HTTPException:
        pass


@client.event
async def on_raw_reaction_remove(p: discord.RawReactionActionEvent):
    if not p.guild_id or (client.user and p.user_id == client.user.id):
        return
    guild = client.get_guild(p.guild_id)
    if not guild:
        return
    panel = rr_find(S(guild), p.message_id)
    if not panel:
        return
    key = emoji_key(p.emoji)
    item = next((it for it in panel.get("items", []) if it.get("roleId") and emoji_key(it.get("emoji", "")) == key), None)
    member = guild.get_member(p.user_id)
    if not item or not member or member.bot:
        return
    try:
        await rr_apply(member, panel, item, False)
    except discord.HTTPException:
        pass


async def reaction_role_button(inter: discord.Interaction, cid: str, s: dict):
    try:
        _, _, panel_id, idx = cid.split(":")
        panel = next(p for p in rr_panels(s) if p.get("id") == panel_id)
        item = panel["items"][int(idx)]
    except (ValueError, StopIteration, IndexError, KeyError):
        return await inter.response.send_message(L(s, "This role message is turned off.", "رسالة الرتب هاي مطفية."), ephemeral=True)
    member = inter.user if isinstance(inter.user, discord.Member) else inter.guild.get_member(inter.user.id)
    role = rr_role(inter.guild, item.get("roleId"))
    if not member or not role:
        return await inter.response.send_message(L(s, "I can't give this role (my role must be above it).", "ما بقدر أعطي هالرتبة (لازم رتبتي تكون فوقها)."), ephemeral=True)
    had = role in member.roles
    try:
        await rr_apply(member, panel, item, not had)
    except discord.HTTPException:
        return await inter.response.send_message(L(s, "Discord refused the role change.", "ديسكورد رفض تغيير الرتبة."), ephemeral=True)
    msg = L(s, f"➖ Removed {role.mention}", f"➖ انشالت منك {role.mention}") if had else L(s, f"✅ You got {role.mention}", f"✅ أخذت {role.mention}")
    await inter.response.send_message(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# ------------------------------------------------------------------ temp voice
TV_BUTTONS = [
    ("name", "✏️"), ("limit", "👥"), ("privacy", "🔒"), ("waiting", "⏳"), ("chat", "💬"),
    ("trust", "✅"), ("untrust", "❎"), ("invite", "📞"), ("kick", "👢"), ("region", "🌍"),
    ("block", "🚫"), ("unblock", "🔓"), ("delete", "🗑️"), ("claim", "👑"), ("transfer", "🔁"),
]
TV_REGIONS = ["automatic", "brazil", "hongkong", "india", "japan", "rotterdam", "russia", "singapore", "southafrica", "sydney", "us-central", "us-east", "us-south", "us-west"]
_tv_cool: dict[tuple, float] = {}
_tv_renames: dict[int, list[float]] = defaultdict(list)


def tv_cfg(s: dict) -> dict:
    return g(s, "tempVoice", {}) or {}


def tv_row(channel_id) -> tuple | None:
    return db.execute("SELECT channel, guild, owner, waiting FROM temp_vc WHERE channel=?", (str(channel_id),)).fetchone()


def tv_panel_embed(s: dict) -> discord.Embed:
    img = str(tv_cfg(s).get("panelImage") or "")
    em = discord.Embed(
        title="Interface - لوحة التحكم",
        description="This interface can be used to manage temporary voice channels.\nيمكن استخدام لوحة التحكم لإدارة القنوات الصوتية المؤقتة.",
        color=0xED4245,
    )
    em.set_image(url=img if img.startswith("http") else f"{SITE_URL}/tempvoice-interface.png")
    em.set_footer(text="Press the buttons below to use the interface.\nاضغط على الأزرار أدناه لاستخدام لوحة التحكم.")
    return em


def tv_panel_view(s: dict) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    custom = tv_cfg(s).get("buttonEmojis") or {}
    for i, (bid, default) in enumerate(TV_BUTTONS):
        v.add_item(discord.ui.Button(emoji=safe_emoji(custom.get(bid), default), style=discord.ButtonStyle.secondary, custom_id=f"peak:tv:{bid}", row=i // 5))
    return v


def tv_name(s: dict, member: discord.Member) -> str:
    n = db.execute("SELECT COUNT(*) FROM temp_vc WHERE guild=?", (str(member.guild.id),)).fetchone()[0] + 1
    t = tv_cfg(s).get("nameTemplate") or "{username}'s room"
    out = t.replace("{username}", member.display_name).replace("{nick}", member.nick or member.display_name).replace("{count}", str(n))
    return (out.strip() or member.display_name)[:100]


async def tv_delete(ch, row):
    db.execute("DELETE FROM temp_vc WHERE channel=?", (str(ch.id),))
    db.commit()
    if row and row[3]:
        w = ch.guild.get_channel(int(row[3]))
        if w:
            try:
                await w.delete(reason="PEAK temp voice: room closed")
            except discord.HTTPException:
                pass
    try:
        await ch.delete(reason="PEAK temp voice: room is empty")
    except discord.HTTPException:
        pass


async def temp_voice_update(member: discord.Member, before_ch, after_ch):
    guild = member.guild
    # Left a temp room: delete it when nobody (human) is left.
    if before_ch is not None:
        row = tv_row(before_ch.id)
        if row and not any(not x.bot for x in before_ch.members):
            await tv_delete(before_ch, row)
    s = S(guild)
    tv = tv_cfg(s)
    if not tv.get("enabled") or after_ch is None or member.bot or str(after_ch.id) != str(tv.get("joinChannelId") or ""):
        return
    # Already has a room: move them back into it instead of making another one.
    mine = db.execute("SELECT channel FROM temp_vc WHERE guild=? AND owner=?", (str(guild.id), str(member.id))).fetchone()
    if mine:
        ch = guild.get_channel(int(mine[0]))
        if ch:
            try:
                await member.move_to(ch)
            except discord.HTTPException:
                pass
            return
        db.execute("DELETE FROM temp_vc WHERE channel=?", (mine[0],))
    key = (guild.id, member.id)
    if time.monotonic() - _tv_cool.get(key, 0) < 15:  # one new room per member every 15s
        return
    _tv_cool[key] = time.monotonic()
    cat = guild.get_channel(int(tv["categoryId"])) if str(tv.get("categoryId") or "").isdigit() else None
    if not isinstance(cat, discord.CategoryChannel):
        cat = after_ch.category
    overwrites = dict(cat.overwrites) if cat else {}
    overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True, move_members=True)
    overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True, send_messages=True, embed_links=True)
    limit = max(0, min(99, int(tv.get("defaultLimit") or 0)))
    ch = await guild.create_voice_channel(tv_name(s, member), category=cat, user_limit=limit, overwrites=overwrites, reason=f"PEAK temp voice for {member}")
    db.execute("INSERT OR REPLACE INTO temp_vc VALUES (?,?,?,?,?)", (str(ch.id), str(guild.id), str(member.id), None, time.time()))
    db.commit()
    try:
        await member.move_to(ch)
    except discord.HTTPException:
        pass
    if member.voice is None or member.voice.channel != ch:
        await asyncio.sleep(1)
        if not any(not x.bot for x in ch.members):
            await tv_delete(ch, tv_row(ch.id))
            return
    if tv.get("panelInVoiceChat", True):
        try:
            await ch.send(content=member.mention, embed=tv_panel_embed(s), view=tv_panel_view(s))
        except discord.HTTPException:
            pass


async def tv_cleanup():
    """Once after start: forget rooms that no longer exist and delete rooms that emptied while offline."""
    await asyncio.sleep(10)
    for ch_id, gid, _owner, waiting in db.execute("SELECT channel, guild, owner, waiting FROM temp_vc").fetchall():
        guild = client.get_guild(int(gid))
        if not guild:
            continue
        ch = guild.get_channel(int(ch_id))
        if not ch:
            db.execute("DELETE FROM temp_vc WHERE channel=?", (ch_id,))
            db.commit()
        elif not any(not x.bot for x in ch.members):
            await tv_delete(ch, (ch_id, gid, _owner, waiting))
            await asyncio.sleep(1)


def tv_room(inter: discord.Interaction):
    """The temp room this click is about: the room whose chat has the panel, else the room the member is in."""
    ch = inter.channel
    if ch is not None and tv_row(ch.id):
        return ch, tv_row(ch.id)
    vs = getattr(inter.user, "voice", None)
    if vs and vs.channel and tv_row(vs.channel.id):
        return vs.channel, tv_row(vs.channel.id)
    return None, None


def tv_text(s: dict, key: str) -> str:
    t = {
        "noroom": ("Join your temp voice room first.", "ادخل رومك الصوتي المؤقت أول."),
        "owner": ("Only the room owner can use this.", "بس صاحب الروم بقدر يستخدم هاد."),
        "done": ("✅ Done.", "✅ تم."),
        "fail": ("❌ Discord refused that action.", "❌ ديسكورد رفض هالعملية."),
        "pick": ("Pick a member:", "اختار عضو:"),
    }[key]
    return L(s, *t)


async def tv_set(ch, target, **perms):
    ow = ch.overwrites_for(target)
    for k, v in perms.items():
        setattr(ow, k, v)
    await ch.set_permissions(target, overwrite=None if ow.is_empty() else ow, reason="PEAK temp voice")


class TVModal(discord.ui.Modal):
    def __init__(self, s: dict, ch, kind: str):
        super().__init__(title=L(s, "Room name", "اسم الروم") if kind == "name" else L(s, "Member limit", "عدد الأعضاء"))
        self.s, self.ch, self.kind = s, ch, kind
        self.field = discord.ui.TextInput(
            label=L(s, "New name", "الاسم الجديد") if kind == "name" else L(s, "0 = no limit, max 99", "0 = بدون حد، أعلى شي 99"),
            default=ch.name[:100] if kind == "name" else str(ch.user_limit or 0),
            max_length=100 if kind == "name" else 2,
        )
        self.add_item(self.field)

    async def on_submit(self, inter: discord.Interaction):
        s, ch = self.s, self.ch
        val = str(self.field.value).strip()
        try:
            if self.kind == "name":
                stamps = [t for t in _tv_renames[ch.id] if time.monotonic() - t < 600]
                if len(stamps) >= 2:  # Discord allows 2 renames per 10 minutes per channel
                    return await inter.response.send_message(L(s, "Discord allows only 2 renames every 10 minutes. Try again later.", "ديسكورد بسمح بتغيير الاسم مرتين كل 10 دقائق بس. جرب بعدين."), ephemeral=True)
                stamps.append(time.monotonic())
                _tv_renames[ch.id] = stamps
                await ch.edit(name=val[:100] or ch.name)
            else:
                await ch.edit(user_limit=max(0, min(99, int(val) if val.isdigit() else 0)))
            await inter.response.send_message(tv_text(s, "done"), ephemeral=True)
        except discord.HTTPException:
            await inter.response.send_message(tv_text(s, "fail"), ephemeral=True)


class TVUserPick(discord.ui.View):
    """Pick any server member (trust / untrust / invite / block / unblock)."""

    def __init__(self, s: dict, ch, kind: str):
        super().__init__(timeout=120)
        self.s, self.ch, self.kind = s, ch, kind
        self.sel = discord.ui.UserSelect(placeholder=tv_text(s, "pick"), min_values=1, max_values=1)
        self.sel.callback = self.picked
        self.add_item(self.sel)

    async def picked(self, inter: discord.Interaction):
        s, ch, kind = self.s, self.ch, self.kind
        target = self.sel.values[0]
        member = inter.guild.get_member(target.id)
        if not member or member.bot:
            return await inter.response.edit_message(content=tv_text(s, "fail"), view=None)
        try:
            if kind == "trust":
                await tv_set(ch, member, connect=True, view_channel=True)
                msg = L(s, f"✅ {member.mention} can always join.", f"✅ {member.mention} بقدر يدخل دايماً.")
            elif kind in ("untrust", "unblock"):
                await ch.set_permissions(member, overwrite=None, reason="PEAK temp voice")
                msg = tv_text(s, "done")
            elif kind == "invite":
                await tv_set(ch, member, connect=True, view_channel=True)
                try:
                    await member.send(L(s, f"📞 {inter.user.mention} invited you to their voice room: {ch.jump_url}", f"📞 {inter.user.mention} عزمك على رومه الصوتي: {ch.jump_url}"))
                    msg = L(s, f"📞 Invite sent to {member.mention}.", f"📞 انبعتت الدعوة لـ {member.mention}.")
                except discord.HTTPException:
                    msg = L(s, f"{member.mention} can join now (their DMs are closed).", f"{member.mention} بقدر يدخل هلأ (الخاص عنده مسكر).")
            else:  # block
                if member.id == inter.user.id:
                    return await inter.response.edit_message(content=tv_text(s, "fail"), view=None)
                await tv_set(ch, member, connect=False)
                if member.voice and member.voice.channel == ch:
                    await member.move_to(None)
                msg = L(s, f"🚫 {member.mention} is blocked from this room.", f"🚫 {member.mention} انحظر من هالروم.")
        except discord.HTTPException:
            msg = tv_text(s, "fail")
        await inter.response.edit_message(content=msg, view=None, allowed_mentions=discord.AllowedMentions.none())


class TVSelect(discord.ui.View):
    """Choice from a list (privacy / region / kick / transfer)."""

    def __init__(self, s: dict, ch, kind: str, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        self.s, self.ch, self.kind = s, ch, kind
        self.sel = discord.ui.Select(placeholder=tv_text(s, "pick") if kind in ("kick", "transfer") else L(s, "Choose…", "اختار…"), options=options[:25])
        self.sel.callback = self.picked
        self.add_item(self.sel)

    async def picked(self, inter: discord.Interaction):
        s, ch, kind, v = self.s, self.ch, self.kind, self.sel.values[0]
        everyone = inter.guild.default_role
        try:
            if kind == "privacy":
                perms = {"lock": {"connect": False}, "unlock": {"connect": None}, "hide": {"view_channel": False}, "unhide": {"view_channel": None}}[v]
                await tv_set(ch, everyone, **perms)
            elif kind == "region":
                await ch.edit(rtc_region=None if v == "automatic" else v)
            elif kind == "kick":
                m = inter.guild.get_member(int(v))
                if m and m.voice and m.voice.channel == ch:
                    await m.move_to(None)
            elif kind == "transfer":
                m = inter.guild.get_member(int(v))
                if not m:
                    return await inter.response.edit_message(content=tv_text(s, "fail"), view=None)
                await tv_give(ch, m)
            await inter.response.edit_message(content=tv_text(s, "done"), view=None)
        except discord.HTTPException:
            await inter.response.edit_message(content=tv_text(s, "fail"), view=None)


class TVConfirmDelete(discord.ui.View):
    def __init__(self, s: dict, ch):
        super().__init__(timeout=60)
        self.s, self.ch = s, ch

    @discord.ui.button(label="Delete / حذف", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def yes(self, inter: discord.Interaction, _b: discord.ui.Button):
        await inter.response.edit_message(content=tv_text(self.s, "done"), view=None)
        await tv_delete(self.ch, tv_row(self.ch.id))


async def tv_give(ch, member: discord.Member):
    row = tv_row(ch.id)
    old = ch.guild.get_member(int(row[2])) if row else None
    db.execute("UPDATE temp_vc SET owner=? WHERE channel=?", (str(member.id), str(ch.id)))
    db.commit()
    await tv_set(ch, member, view_channel=True, connect=True, speak=True, stream=True, move_members=True)
    if old and old.id != member.id:
        await tv_set(ch, old, move_members=None)


async def tv_button(inter: discord.Interaction, action: str, s: dict):
    ch, row = tv_room(inter)
    if not ch:
        return await inter.response.send_message(tv_text(s, "noroom"), ephemeral=True)
    owner_id = int(row[2])
    me = inter.user
    is_owner = me.id == owner_id or (isinstance(me, discord.Member) and is_mod(me))
    if action == "claim":
        owner = inter.guild.get_member(owner_id)
        if me.id == owner_id:
            return await inter.response.send_message(L(s, "You already own this room.", "إنت صاحب الروم أصلاً."), ephemeral=True)
        if owner and owner.voice and owner.voice.channel == ch:
            return await inter.response.send_message(L(s, "The owner is still in the room.", "صاحب الروم لسا موجود فيه."), ephemeral=True)
        if not (me.voice and me.voice.channel == ch):
            return await inter.response.send_message(tv_text(s, "noroom"), ephemeral=True)
        try:
            await tv_give(ch, me)
        except discord.HTTPException:
            return await inter.response.send_message(tv_text(s, "fail"), ephemeral=True)
        return await inter.response.send_message(L(s, f"👑 {me.mention} owns this room now.", f"👑 {me.mention} صار صاحب الروم."), allowed_mentions=discord.AllowedMentions.none())
    if not is_owner:
        return await inter.response.send_message(tv_text(s, "owner"), ephemeral=True)

    everyone = inter.guild.default_role
    if action in ("name", "limit"):
        return await inter.response.send_modal(TVModal(s, ch, action))
    if action in ("trust", "untrust", "invite", "block", "unblock"):
        return await inter.response.send_message(tv_text(s, "pick"), view=TVUserPick(s, ch, action), ephemeral=True)
    if action == "privacy":
        opts = [
            discord.SelectOption(label=L(s, "Lock (nobody new can join)", "قفل (ما حدا جديد بقدر يدخل)"), value="lock", emoji="🔒"),
            discord.SelectOption(label=L(s, "Unlock", "فتح"), value="unlock", emoji="🔓"),
            discord.SelectOption(label=L(s, "Hide the room", "إخفاء الروم"), value="hide", emoji="🙈"),
            discord.SelectOption(label=L(s, "Show the room", "إظهار الروم"), value="unhide", emoji="👁️"),
        ]
        return await inter.response.send_message(L(s, "Room privacy:", "خصوصية الروم:"), view=TVSelect(s, ch, "privacy", opts), ephemeral=True)
    if action == "region":
        opts = [discord.SelectOption(label=r, value=r, emoji="🌍") for r in TV_REGIONS]
        return await inter.response.send_message(L(s, "Voice region:", "منطقة الصوت:"), view=TVSelect(s, ch, "region", opts), ephemeral=True)
    if action in ("kick", "transfer"):
        people = [m for m in ch.members if not m.bot and m.id != me.id][:25]
        if not people:
            return await inter.response.send_message(L(s, "Nobody else is in the room.", "ما في حدا ثاني بالروم."), ephemeral=True)
        opts = [discord.SelectOption(label=m.display_name[:100], value=str(m.id)) for m in people]
        return await inter.response.send_message(tv_text(s, "pick"), view=TVSelect(s, ch, action, opts), ephemeral=True)
    if action == "delete":
        return await inter.response.send_message(L(s, "Delete this room?", "متأكد بدك تحذف الروم؟"), view=TVConfirmDelete(s, ch), ephemeral=True)
    try:
        if action == "chat":
            ow = ch.overwrites_for(everyone)
            off = ow.send_messages is False
            await tv_set(ch, everyone, send_messages=None if off else False)
            msg = L(s, "💬 Chat is open." if off else "💬 Chat is closed.", "💬 الشات انفتح." if off else "💬 الشات تسكّر.")
        elif action == "waiting":
            wid = row[3]
            w = inter.guild.get_channel(int(wid)) if wid else None
            if w:
                await w.delete(reason="PEAK temp voice: waiting room off")
                db.execute("UPDATE temp_vc SET waiting=NULL WHERE channel=?", (str(ch.id),))
                db.commit()
                await tv_set(ch, everyone, connect=None)
                msg = L(s, "⏳ Waiting room removed, the room is open.", "⏳ انشالت غرفة الانتظار، والروم مفتوح.")
            else:
                await inter.response.defer(ephemeral=True, thinking=True)
                owner = inter.guild.get_member(owner_id) or me
                ow = {owner: discord.PermissionOverwrite(move_members=True, connect=True, view_channel=True), inter.guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True, manage_channels=True)}
                w = await inter.guild.create_voice_channel(f"⏳ {ch.name}"[:100], category=ch.category, overwrites={**(dict(ch.category.overwrites) if ch.category else {}), **ow}, reason="PEAK temp voice: waiting room")
                db.execute("UPDATE temp_vc SET waiting=? WHERE channel=?", (str(w.id), str(ch.id)))
                db.commit()
                await tv_set(ch, everyone, connect=False)
                return await inter.followup.send(L(s, f"⏳ Waiting room {w.mention} created. People wait there and you drag them in.", f"⏳ انعملت غرفة انتظار {w.mention}. الناس بستنوا فيها وإنت بتسحبهم لرومك."), ephemeral=True)
        else:
            return await inter.response.send_message(tv_text(s, "fail"), ephemeral=True)
    except discord.HTTPException:
        msg = tv_text(s, "fail")
    if inter.response.is_done():
        await inter.followup.send(msg, ephemeral=True)
    else:
        await inter.response.send_message(msg, ephemeral=True)


# ------------------------------------------------------------------ data backup on the website
# XP, bank, warnings and open tickets live in the local peak.db file. Many hosts (e.g. Render) wipe
# local files on every deploy, so a compressed copy is also kept on the website. When the bot starts
# with an empty peak.db, it restores that copy first. This only talks to the website, never Discord.
BACKUP_TABLES = ["xp", "tickets", "warns", "app_cool", "bank", "bank_cool", "ticket_seq", "game_stats", "meta", "temp_vc"]
DATA_TABLES = ["xp", "tickets", "warns", "bank", "game_stats", "ticket_seq"]


def local_rows() -> int:
    return sum(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in DATA_TABLES)


def dump_db() -> tuple[str, str, int]:
    out = {}
    for t in BACKUP_TABLES:
        cur = db.execute(f"SELECT * FROM {t}")
        out[t] = {"cols": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
    raw = json.dumps(out, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    return base64.b64encode(gzip.compress(raw)).decode(), hashlib.sha256(raw).hexdigest(), local_rows()


def load_db(data: str) -> int:
    """Adds the backup rows to the local database (rows that already exist are kept as they are)."""
    obj = json.loads(gzip.decompress(base64.b64decode(data)))
    n = 0
    for t, blob in obj.items():
        if t not in BACKUP_TABLES:
            continue
        have = {r[1] for r in db.execute(f"PRAGMA table_info({t})")}
        cols = [c for c in blob.get("cols", []) if c in have]
        if not cols:
            continue
        idx = [blob["cols"].index(c) for c in cols]
        rows = [[row[i] for i in idx] for row in blob.get("rows", [])]
        db.executemany(f"INSERT OR IGNORE INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", rows)
        n += len(rows)
    db.commit()
    return n


async def restore_backup():
    """Only when peak.db is empty (fresh host): bring back the copy kept on the website."""
    try:
        if local_rows() > 0:
            return
        async with http.get(f"{SITE_URL}/api/public/bot/backup", headers={"Authorization": f"Bearer {SYNC_KEY}"}, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                return
            body = await r.json(content_type=None)
        data = ((body or {}).get("backup") or {}).get("data")
        if data:
            print(f"Restored {load_db(data)} saved rows (XP, bank, tickets…) from the website backup.")
    except Exception as e:  # noqa: BLE001
        print("backup restore skipped:", e)


async def backup_loop():
    await client.wait_until_ready()
    last = None
    await asyncio.sleep(60)
    while True:
        wait = 300
        try:
            data, h, rows = dump_db()
            if h != last:
                async with http.put(
                    f"{SITE_URL}/api/public/bot/backup",
                    json={"data": data, "hash": h, "rows": rows},
                    headers={"Authorization": f"Bearer {SYNC_KEY}"},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as r:
                    if r.status == 200:
                        last = h
                    elif r.status == 409:
                        print("Website kept its bigger backup instead of this almost empty one. Restart the bot to restore it.")
                        wait = 3600
                    elif r.status in (404, 405):
                        print("The website does not have the backup feature yet: upload the latest website files.")
                        wait = 3600
                    else:
                        print(f"Website answered {r.status} to the data backup.")
        except Exception as e:  # noqa: BLE001
            print("backup failed:", e)
        await asyncio.sleep(wait)


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
    asyncio.create_task(interest_loop())  # daily bank interest (local only)
    asyncio.create_task(backup_loop())  # keeps a copy of XP / bank / tickets on the website
    asyncio.create_task(tv_cleanup())  # removes temp voice rooms that emptied while the bot was offline
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
    # A freshly wiped host gets its XP / bank / tickets back before anything new is written.
    await restore_backup()
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
