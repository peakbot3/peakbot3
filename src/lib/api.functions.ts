import { createServerFn } from "@tanstack/react-start";
import { getRequest } from "@tanstack/react-start/server";
import { z } from "zod";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { appIdFromToken, botFetch, botGuildIdSet, botGuildIds, clearBotGuildCache, dfetch, forgetRejectedToken, getBotConfig, guildBasics, siteOrigin, userGuilds } from "./discord.server";
import { getSnapshot } from "./guild-cache.server";
import { getAppSession } from "./session.server";
import { getBotStatus } from "./bot-status.server";
import { ADMIN_DISCORD_ID, deepMerge, defaultSettings } from "./settings";

const snowflake = z.string().regex(/^\d{5,25}$/);
const ADMIN_PERM = 0x8n;
// Permissions the bot asks for when invited (admin keeps setup simple for welcome, tickets, protection, logs).
const INVITE_PERMS = "8";

function safeEq(a: string, b: string) {
  const x = createHash("sha256").update(a).digest();
  const y = createHash("sha256").update(b).digest();
  return timingSafeEqual(x, y);
}

async function admin() {
  const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
  return supabaseAdmin;
}

async function requireAdmin() {
  const s = await getAppSession();
  if (!s.data.admin) throw new Error("Forbidden");
  return s;
}

function canManage(g: { owner: boolean; permissions: string }) {
  return g.owner || (BigInt(g.permissions) & ADMIN_PERM) === ADMIN_PERM;
}

async function requireGuildAccess(guildId: string) {
  const s = await getAppSession();
  if (s.data.admin) return s;
  if (!s.data.user || !s.data.accessToken) throw new Error("Please sign in with Discord first.");
  if (s.data.manageable?.includes(guildId)) return s;
  // Opened a server page directly (no list loaded yet): check with the cached guild list.
  const all = await userGuilds(s.data.user.id, s.data.accessToken);
  if (!all) {
    await s.clear();
    throw new Error("Please sign in with Discord first.");
  }
  const mine = all.filter(canManage).map((g) => g.id);
  await s.update({ manageable: mine });
  if (!mine.includes(guildId)) throw new Error("You need Administrator permission in this server.");
  return s;
}

// ---------- session ----------
export const getSessionInfo = createServerFn({ method: "GET" }).handler(async () => {
  const s = await getAppSession();
  // Never fail the whole session check when the database / bot config has a problem:
  // the admin must still be able to open the panel and see what is wrong.
  const cfg = await getBotConfig();
  const setupError = cfg.dbError;
  return {
    user: s.data.user ?? null,
    admin: !!s.data.admin,
    botReady: !!(cfg?.client_id && cfg?.bot_token),
    loginReady: !!(cfg?.client_id && cfg?.client_secret),
    clientId: cfg?.client_id ?? null,
    setupError: s.data.admin ? setupError : setupError ? "setup" : null,
  };
});

export const adminLogin = createServerFn({ method: "POST" })
  .inputValidator((d: { id: string; password: string }) => z.object({ id: z.string().max(40), password: z.string().max(200) }).parse(d))
  .handler(async ({ data }) => {
    const expected = process.env["ADMIN_PASSWORD"];
    if (!expected) throw new Error("ADMIN_PASSWORD is not set");
    await new Promise((r) => setTimeout(r, 600)); // slow down guessing
    const ok = safeEq(data.id.trim(), ADMIN_DISCORD_ID) && safeEq(data.password, expected);
    if (!ok) return { ok: false as const };
    const s = await getAppSession();
    await s.update({ admin: true });
    return { ok: true as const };
  });

export const logout = createServerFn({ method: "POST" }).handler(async () => {
  const s = await getAppSession();
  await s.clear();
  return { ok: true };
});

// ---------- public ----------
export const getPublicStats = createServerFn({ method: "GET" }).handler(async () => {
  let data: { servers: number; users: number; active_tickets: number } | null = null;
  try {
    const db = await admin();
    data = (await db.from("bot_stats").select("servers,users,active_tickets").eq("id", 1).abortSignal(AbortSignal.timeout(8000)).single()).data;
  } catch (e) {
    console.error("bot_stats unavailable:", (e as Error).message);
  }
  const cfg = await getBotConfig();
  return {
    servers: data?.servers ?? 0,
    users: data?.users ?? 0,
    tickets: data?.active_tickets ?? 0,
    inviteUrl: cfg.client_id
      ? `https://discord.com/oauth2/authorize?client_id=${cfg.client_id}&permissions=${INVITE_PERMS}&scope=bot%20applications.commands`
      : null,
  };
});

// ---------- user dashboard ----------
export const listMyGuilds = createServerFn({ method: "GET" }).handler(async () => {
  const s = await getAppSession();
  if (!s.data.user || !s.data.accessToken) return { signedIn: false as const, guilds: [] };
  const all = await userGuilds(s.data.user.id, s.data.accessToken);
  if (!all) {
    await s.clear();
    return { signedIn: false as const, guilds: [] };
  }
  const mine = all.filter(canManage);
  let botIds = new Set<string>();
  try {
    botIds = await botGuildIdSet();
  } catch {
    /* bot not configured yet */
  }
  await s.update({ manageable: mine.map((g) => g.id) });
  const cfg = await getBotConfig();
  return {
    signedIn: true as const,
    guilds: mine
      .map((g) => ({
        id: g.id,
        name: g.name,
        icon: g.icon,
        botIn: botIds.has(g.id),
        inviteUrl: cfg.client_id
          ? `https://discord.com/oauth2/authorize?client_id=${cfg.client_id}&permissions=${INVITE_PERMS}&scope=bot%20applications.commands&guild_id=${g.id}&disable_guild_select=true`
          : null,
      }))
      .sort((a, b) => Number(b.botIn) - Number(a.botIn)),
  };
});

export const getGuildData = createServerFn({ method: "GET" })
  .inputValidator((d: { guildId: string }) => z.object({ guildId: snowflake }).parse(d))
  .handler(async ({ data }) => {
    await requireGuildAccess(data.guildId);
    // Read from what the bot already knows; the Discord API is only a cached fallback.
    const basics = await guildBasics(data.guildId);
    if (basics.botMissing) return { botMissing: true as const };
    const db = await admin();
    const { data: row } = await db.from("guild_settings").select("settings").eq("guild_id", data.guildId).maybeSingle();
    return {
      botMissing: false as const,
      guild: basics.guild,
      channels: basics.channels.map((c) => ({ id: c.id, name: c.name, type: c.type, parentId: c.parent_id })),
      roles: basics.roles.map((r) => ({ id: r.id, name: r.name, color: r.color, managed: r.managed })),
      emojis: basics.emojis,
      settings: deepMerge(defaultSettings(), row?.settings ?? {}),
    };
  });

/**
 * Values only the website writes (bot picture link, posted role-message ids) are kept from the saved
 * copy, so an older open tab can never wipe them when it saves.
 */
function keepServerOwned(next: Saved, prev: Saved | null) {
  if (!prev) return;
  if (next.general && typeof next.general === "object") next.general["botAvatar"] = prev.general?.["botAvatar"] ?? "";
  const old = new Map((prev.reactionRoles?.panels ?? []).map((p) => [p.id, p]));
  for (const p of next.reactionRoles?.panels ?? []) {
    const o = old.get(p.id);
    if (o && !p.messageId && o.messageId && o.channelId === p.channelId) p.messageId = o.messageId;
  }
}

export const saveGuildSettings = createServerFn({ method: "POST" })
  .inputValidator((d: { guildId: string; settings: unknown }) =>
    z.object({ guildId: snowflake, settings: z.record(z.string(), z.unknown()) }).parse(d),
  )
  .handler(async ({ data }) => {
    await requireGuildAccess(data.guildId);
    if (JSON.stringify(data.settings).length > 200_000) throw new Error("Settings are too large.");
    const db = await admin();
    const { data: prev } = await db.from("guild_settings").select("settings").eq("guild_id", data.guildId).maybeSingle();
    keepServerOwned(data.settings as Saved, (prev?.settings ?? null) as Saved | null);
    const { error } = await db
      .from("guild_settings")
      .upsert({ guild_id: data.guildId, settings: data.settings as never, updated_at: new Date().toISOString() });
    if (error) throw new Error(error.message);
    // Apply the bot nickname right away, but only when it actually changed (one call, not one per save).
    const nick = (data.settings as { general?: { nickname?: string } }).general?.nickname;
    const prevNick = (prev?.settings as { general?: { nickname?: string } } | null | undefined)?.general?.nickname;
    if (typeof nick === "string" && (prev == null || nick !== (prevNick ?? ""))) {
      await botFetch(`/guilds/${data.guildId}/members/@me`, { method: "PATCH", body: JSON.stringify({ nick: nick || null }) }).catch(() => null);
    }
    return { ok: true };
  });

const embedSchema = z.object({
  title: z.string().max(256).optional(),
  description: z.string().max(4096).optional(),
  color: z.number().int().optional(),
  image: z.object({ url: z.string().url() }).optional(),
  thumbnail: z.object({ url: z.string().url() }).optional(),
  footer: z.object({ text: z.string().max(2048) }).optional(),
  author: z.object({ name: z.string().max(256) }).optional(),
});

export const sendToChannel = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z
      .object({
        guildId: snowflake,
        channelId: snowflake,
        content: z.string().max(2000).optional(),
        embeds: z.array(embedSchema).max(10).optional(),
        components: z.array(z.any()).max(5).optional(),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    await requireGuildAccess(data.guildId);
    // The bot's server info already says which channels belong to this server: no extra Discord call.
    const snap = getSnapshot(data.guildId);
    if (snap) {
      if (!snap.channels.some((c) => c.id === data.channelId)) throw new Error("That channel is not in this server.");
    } else {
      const ch = await botFetch(`/channels/${data.channelId}`);
      const chJson = (await ch.json()) as { guild_id?: string };
      if (!ch.ok || chJson.guild_id !== data.guildId) throw new Error("That channel is not in this server.");
    }
    const res = await botFetch(`/channels/${data.channelId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: data.content, embeds: data.embeds, components: data.components, allowed_mentions: { parse: [] } }),
    });
    if (!res.ok) throw new Error(`Discord refused the message (${res.status}): ${await res.text()}`);
    const msg = (await res.json().catch(() => ({}))) as { id?: string };
    return { ok: true, id: msg.id ?? null };
  });

// ---------- helpers for the new modules ----------
type Saved = Record<string, unknown> & {
  general?: Record<string, unknown>;
  reactionRoles?: { panels?: { id: string; channelId: string; messageId: string; mode: string; unique: boolean; embed: Record<string, string>; items: { emoji: string; roleId: string; label: string }[] }[] };
};

async function readSaved(guildId: string): Promise<Saved> {
  const db = await admin();
  const { data: row } = await db.from("guild_settings").select("settings").eq("guild_id", guildId).maybeSingle();
  return ((row?.settings as Saved | null) ?? {}) as Saved;
}

async function writeSaved(guildId: string, settings: Saved) {
  const db = await admin();
  const { error } = await db.from("guild_settings").upsert({ guild_id: guildId, settings: settings as never, updated_at: new Date().toISOString() });
  if (error) throw new Error(error.message);
}

async function assertChannelInGuild(guildId: string, channelId: string) {
  const snap = getSnapshot(guildId);
  if (snap) {
    if (!snap.channels.some((c) => c.id === channelId)) throw new Error("That channel is not in this server.");
    return;
  }
  const ch = await botFetch(`/channels/${channelId}`);
  const chJson = (await ch.json()) as { guild_id?: string };
  if (!ch.ok || chJson.guild_id !== guildId) throw new Error("That channel is not in this server.");
}

/** "<:name:id>", "<a:name:id>" or a normal emoji -> parts Discord understands. */
function parseEmoji(v: string): { id: string | null; name: string; animated: boolean } | null {
  const t = (v ?? "").trim();
  if (!t) return null;
  const m = /^<(a?):([\w~]{1,32}):(\d{5,25})>$/.exec(t);
  if (m) return { id: m[3]!, name: m[2]!, animated: m[1] === "a" };
  return { id: null, name: t, animated: false };
}

function hexColor(c: string | undefined) {
  return parseInt(String(c || "#22d3ee").replace("#", ""), 16) || 0;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Posts (or updates) a reaction-role message from the SAVED settings, adds its emoji reactions,
 * and remembers the message id so the bot knows which message gives which role.
 */
export const sendReactionRolePanel = createServerFn({ method: "POST" })
  .inputValidator((d: { guildId: string; panelId: string }) => z.object({ guildId: snowflake, panelId: z.string().min(1).max(40) }).parse(d))
  .handler(async ({ data }) => {
    await requireGuildAccess(data.guildId);
    const saved = await readSaved(data.guildId);
    const panels = saved.reactionRoles?.panels ?? [];
    const panel = panels.find((p) => p.id === data.panelId);
    if (!panel) throw new Error("Save your changes first, then send the message.");
    if (!panel.channelId) throw new Error("Pick a channel for this message first.");
    const items = (panel.items ?? []).filter((i) => i.roleId && parseEmoji(i.emoji));
    if (!items.length) throw new Error("Add at least one emoji with a role.");
    await assertChannelInGuild(data.guildId, panel.channelId);
    const e = panel.embed ?? {};
    const embed: Record<string, unknown> = { color: hexColor(e["color"]) };
    if (e["title"]) embed["title"] = String(e["title"]).slice(0, 256);
    if (e["description"]) embed["description"] = String(e["description"]).slice(0, 4096);
    if (/^https?:\/\//.test(e["imageUrl"] ?? "")) embed["image"] = { url: e["imageUrl"] };
    if (/^https?:\/\//.test(e["thumbnailUrl"] ?? "")) embed["thumbnail"] = { url: e["thumbnailUrl"] };
    if (e["footer"]) embed["footer"] = { text: String(e["footer"]).slice(0, 2048) };
    const buttons = panel.mode === "buttons";
    const components: object[] = [];
    if (buttons) {
      const list = items.slice(0, 25);
      for (let r = 0; r < list.length; r += 5) {
        components.push({
          type: 1,
          components: list.slice(r, r + 5).map((it) => {
            const em = parseEmoji(it.emoji)!;
            const idx = panel.items.indexOf(it);
            return {
              type: 2,
              style: 2,
              custom_id: `peak:rr:${panel.id}:${idx}`,
              label: (it.label || "").slice(0, 80) || undefined,
              emoji: em.id ? { id: em.id, name: em.name, animated: em.animated } : { name: em.name },
            };
          }),
        });
      }
    }
    const body = JSON.stringify({ embeds: [embed], components, allowed_mentions: { parse: [] } });
    let messageId = panel.messageId || "";
    let res: Response | null = null;
    if (messageId) {
      // Already posted before: update that message instead of posting a second one.
      res = await botFetch(`/channels/${panel.channelId}/messages/${messageId}`, { method: "PATCH", body });
      if (!res.ok) messageId = "";
    }
    if (!messageId) {
      res = await botFetch(`/channels/${panel.channelId}/messages`, { method: "POST", body });
      if (!res.ok) throw new Error(`Discord refused the message (${res.status}): ${await res.text()}`);
      messageId = ((await res.json()) as { id: string }).id;
    }
    if (!buttons) {
      // One reaction at a time with a pause: Discord allows only a few reactions per second.
      for (const it of items.slice(0, 20)) {
        const em = parseEmoji(it.emoji)!;
        const code = encodeURIComponent(em.id ? `${em.name}:${em.id}` : em.name);
        await botFetch(`/channels/${panel.channelId}/messages/${messageId}/reactions/${code}/@me`, { method: "PUT" }).catch(() => null);
        await sleep(350);
      }
    }
    panel.messageId = messageId;
    await writeSaved(data.guildId, saved);
    return { ok: true, messageId };
  });

/** Bot picture for ONE server only (Discord "server profile"). Other servers keep the normal picture. */
export const setBotServerAvatar = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z
      .object({
        guildId: snowflake,
        kind: z.enum(["upload", "serverIcon", "reset"]),
        dataUri: z
          .string()
          .max(6_000_000)
          .regex(/^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/)
          .optional(),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    await requireGuildAccess(data.guildId);
    let avatar: string | null = null;
    if (data.kind === "upload") {
      if (!data.dataUri) throw new Error("Pick a picture first.");
      avatar = data.dataUri;
    } else if (data.kind === "serverIcon") {
      const basics = await guildBasics(data.guildId);
      if (basics.botMissing || !basics.guild.icon) throw new Error("This server has no icon.");
      const animated = basics.guild.icon.startsWith("a_");
      const img = await fetch(`https://cdn.discordapp.com/icons/${data.guildId}/${basics.guild.icon}.${animated ? "gif" : "png"}?size=512`);
      if (!img.ok) throw new Error("Could not load the server icon.");
      const bytes = new Uint8Array(await img.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      avatar = `data:image/${animated ? "gif" : "png"};base64,${btoa(bin)}`;
    }
    const res = await botFetch(`/guilds/${data.guildId}/members/@me`, { method: "PATCH", body: JSON.stringify({ avatar }) });
    if (!res.ok) {
      const txt = await res.text();
      if (res.status === 429) throw new Error("Discord allows only a few picture changes in a short time. Try again in a few minutes.");
      throw new Error(`Discord refused the picture (${res.status}): ${txt.slice(0, 300)}`);
    }
    const member = (await res.json()) as { avatar?: string | null; user?: { id: string } };
    const url =
      member.avatar && member.user?.id
        ? `https://cdn.discordapp.com/guilds/${data.guildId}/users/${member.user.id}/avatars/${member.avatar}.${member.avatar.startsWith("a_") ? "gif" : "png"}?size=256`
        : "";
    const saved = await readSaved(data.guildId);
    saved.general = { ...(saved.general ?? {}), botAvatar: url };
    await writeSaved(data.guildId, saved);
    return { ok: true, url };
  });

// ---------- admin ----------
const botUserCache = new Map<string, { at: number; value: { id: string; username: string; avatar: string | null } | null }>();

export const getBotCredentials = createServerFn({ method: "GET" }).handler(async () => {
  await requireAdmin();
  const cfg = await getBotConfig();
  const req = getRequest();
  let botUser: { id: string; username: string; avatar: string | null } | null = null;
  if (cfg.bot_token) {
    // Checked at most every 5 minutes per token, so opening the admin panel never spams Discord.
    const hit = botUserCache.get(cfg.bot_token);
    if (hit && Date.now() - hit.at < 5 * 60_000) botUser = hit.value;
    else {
      const r = await botFetch("/users/@me").catch(() => null);
      if (r?.ok) botUser = await r.json();
      if (r) {
        botUserCache.clear();
        botUserCache.set(cfg.bot_token, { at: Date.now(), value: botUser });
      }
    }
  }
  let stats: { servers: number; users: number; active_tickets: number } | null = null;
  try {
    const db = await admin();
    const r = await db.from("bot_stats").select("*").eq("id", 1).abortSignal(AbortSignal.timeout(8000)).single();
    stats = r.data;
  } catch (e) {
    console.error("bot_stats unavailable:", (e as Error).message);
  }
  const origin = req ? siteOrigin(req) : "";
  return {
    clientId: cfg.client_id ?? "",
    clientSecret: cfg.client_secret ?? "",
    botToken: cfg.bot_token ?? "",
    syncKey: cfg.sync_key ?? "",
    lastPing: cfg.last_bot_ping,
    botStatus: getBotStatus(),
    botUser,
    stats,
    redirectUri: `${origin}/api/auth/discord/callback`,
    siteUrl: origin,
  };
});

export const saveBotCredentials = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z.object({ clientId: z.string().max(30), clientSecret: z.string().max(200), botToken: z.string().max(200) }).parse(d),
  )
  .handler(async ({ data }) => {
    await requireAdmin();
    const botToken = data.botToken.trim();
    const clientSecret = data.clientSecret.trim();
    let clientId = data.clientId.trim();
    const tokenAppId = botToken ? appIdFromToken(botToken) : null;
    if (botToken && (!tokenAppId || botToken.split(".").length !== 3)) {
      throw new Error("The Bot Token looks wrong. Copy it from Discord Developer Portal → Bot → Reset Token.");
    }
    if (!clientId && tokenAppId) clientId = tokenAppId;
    if (clientId && !/^\d{17,20}$/.test(clientId)) {
      throw new Error("The Application ID must be a number. Copy it from Developer Portal → General Information.");
    }
    if (tokenAppId && clientId !== tokenAppId) {
      throw new Error(
        `The Application ID does not match this Bot Token. It must be ${tokenAppId} (Developer Portal → General Information → Application ID), not your own Discord user ID.`,
      );
    }
    if (clientSecret && (/^\d+$/.test(clientSecret) || clientSecret === clientId || clientSecret.length < 20)) {
      throw new Error("The Client Secret looks wrong. Copy it from Developer Portal → OAuth2 → Client Secret (Reset Secret). It is not an ID.");
    }
    if (botToken) {
      // One check with Discord so a wrong token is caught now instead of failing again and again later.
      const r = await dfetch("/users/@me", { headers: { Authorization: `Bot ${botToken}` } });
      if (r.status === 401) throw new Error("Discord rejected this Bot Token. Reset it in Developer Portal → Bot and paste the new one.");
    }
    const db = await admin();
    const { error } = await db
      .from("bot_config")
      .upsert({ id: 1, client_id: clientId || null, client_secret: clientSecret || null, bot_token: botToken || null, updated_at: new Date().toISOString() });
    if (error) throw new Error(error.message);
    clearBotGuildCache();
    forgetRejectedToken();
    botUserCache.clear();
    return { ok: true };
  });

export const regenerateSyncKey = createServerFn({ method: "POST" }).handler(async () => {
  await requireAdmin();
  const db = await admin();
  await db.from("bot_config").update({ sync_key: randomBytes(24).toString("hex") }).eq("id", 1);
  return { ok: true };
});

export const adminListBotGuilds = createServerFn({ method: "GET" }).handler(async () => {
  await requireAdmin();
  try {
    return { guilds: await botGuildIds(), error: null };
  } catch (e) {
    return { guilds: [], error: (e as Error).message };
  }
});
