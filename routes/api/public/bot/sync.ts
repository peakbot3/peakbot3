import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { BACKUP_ROW } from "@/lib/bot-backup";

// Endpoint the PEAK Python bot polls. Authenticated with the sync key shown in the admin panel.
const statusSchema = z.object({
  status: z.enum(["starting", "no_token", "bad_token", "intents", "rate_limited", "network", "error", "online"]),
  detail: z.string().max(300).optional(),
});

const statsSchema = z.object({
  servers: z.number().int().min(0).max(1e9),
  users: z.number().int().min(0).max(1e10),
  active_tickets: z.number().int().min(0).max(1e9),
  guild_ids: z.array(z.string().regex(/^\d+$/)).max(10000),
});

const id = z.string().regex(/^\d{5,25}$/);
// Server info the bot already has from its Discord connection (no Discord API call needed).
const snapshotSchema = z.object({
  snapshots: z
    .array(
      z.object({
        id,
        name: z.string().max(200),
        icon: z.string().max(100).nullable(),
        member_count: z.number().int().min(0).max(1e8),
        channels: z
          .array(z.object({ id, name: z.string().max(200), type: z.number().int(), parent_id: id.nullable(), position: z.number().int() }))
          .max(1500),
        roles: z
          .array(z.object({ id, name: z.string().max(200), color: z.number().int(), position: z.number().int(), managed: z.boolean() }))
          .max(1000),
        emojis: z
          .array(z.object({ id, name: z.string().max(100), animated: z.boolean() }))
          .max(2000)
          .optional(),
      }),
    )
    .max(50),
  removed: z.array(id).max(10000).default([]),
  all_ids: z.array(id).max(10000),
});

export const Route = createFileRoute("/api/public/bot/sync")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const v = await (await import("@/lib/bot-auth.server")).verifyBot(request);
        if (!v) return new Response("Unauthorized", { status: 401 });
        const since = new URL(request.url).searchParams.get("since");
        // The bot's data backup lives in its own row (see bot/backup.ts); never send it as server settings.
        let q = v.db.from("guild_settings").select("guild_id,settings,updated_at").neq("guild_id", BACKUP_ROW);
        if (since) q = q.gt("updated_at", since);
        const { data } = await q;
        // Settings are stored encrypted; the bot receives them unlocked. Rows saved before encryption
        // are encrypted now (updated_at is left as it is, so the bot does not see a fake change).
        const { openSettings, isSealed, sealSettings } = await import("@/lib/settings-store.server");
        const guilds = [];
        for (const row of data ?? []) {
          const settings = openSettings(row.settings);
          if (settings == null) continue; // cannot be unlocked: never send empty settings that would switch features off
          if (!isSealed(row.settings)) {
            await v.db.from("guild_settings").update({ settings: sealSettings(settings) as never }).eq("guild_id", row.guild_id);
          }
          guilds.push({ ...row, settings });
        }
        return Response.json({ token: v.cfg.bot_token, client_id: v.cfg.client_id, guilds, now: new Date().toISOString() });
      },
      POST: async ({ request }) => {
        const v = await (await import("@/lib/bot-auth.server")).verifyBot(request);
        if (!v) return new Response("Unauthorized", { status: 401 });
        const body = await request.json().catch(() => null);
        const st = statusSchema.safeParse(body);
        if (st.success) {
          const { setBotStatus } = await import("@/lib/bot-status.server");
          setBotStatus(st.data.status, st.data.detail ?? "");
          return Response.json({ ok: true });
        }
        const snap = snapshotSchema.safeParse(body);
        if (snap.success) {
          const { putSnapshots, setBotGuildIds } = await import("@/lib/guild-cache.server");
          setBotGuildIds(snap.data.all_ids);
          const held = putSnapshots(snap.data.snapshots, snap.data.removed);
          return Response.json({ ok: true, held });
        }
        const parsed = statsSchema.safeParse(body);
        if (!parsed.success) return new Response("Bad request", { status: 400 });
        const now = new Date().toISOString();
        await v.db.from("bot_stats").update({ ...parsed.data, updated_at: now }).eq("id", 1);
        await v.db.from("bot_config").update({ last_bot_ping: now }).eq("id", 1);
        const { setBotStatus } = await import("@/lib/bot-status.server");
        setBotStatus("online");
        const { setBotGuildIds, snapshotCount } = await import("@/lib/guild-cache.server");
        setBotGuildIds(parsed.data.guild_ids);
        // Lets the bot notice a website restart and re-send the server info it holds.
        return Response.json({ ok: true, snapshots: snapshotCount() });
      },
    },
  },
});
