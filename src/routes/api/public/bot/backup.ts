import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { BACKUP_ROW, MAX_BACKUP_CHARS } from "@/lib/bot-backup";

// Backup of the bot's local data (XP, bank, warnings, open tickets). Only the bot, with the sync key, can use it.
const putSchema = z.object({
  data: z.string().max(MAX_BACKUP_CHARS).regex(/^[A-Za-z0-9+/=]*$/),
  hash: z.string().regex(/^[a-f0-9]{64}$/),
  rows: z.number().int().min(0).max(1e8),
});

export const Route = createFileRoute("/api/public/bot/backup")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const v = await (await import("@/lib/bot-auth.server")).verifyBot(request);
        if (!v) return new Response("Unauthorized", { status: 401 });
        const { data, error } = await v.db.from("guild_settings").select("settings,updated_at").eq("guild_id", BACKUP_ROW).maybeSingle();
        if (error) return new Response("Backup unavailable", { status: 503 });
        return Response.json({ backup: data?.settings ?? null, updated_at: data?.updated_at ?? null }, { headers: { "cache-control": "no-store" } });
      },
      PUT: async ({ request }) => {
        const v = await (await import("@/lib/bot-auth.server")).verifyBot(request);
        if (!v) return new Response("Unauthorized", { status: 401 });
        const parsed = putSchema.safeParse(await request.json().catch(() => null));
        if (!parsed.success) return new Response("Bad request", { status: 400 });
        const { data: prev } = await v.db.from("guild_settings").select("settings").eq("guild_id", BACKUP_ROW).maybeSingle();
        const prevRows = Number((prev?.settings as { rows?: number } | null)?.rows ?? 0);
        // Safety net: a nearly empty upload never replaces a big backup (a freshly wiped bot must restore, not overwrite).
        if (prevRows > 20 && parsed.data.rows < prevRows * 0.2) {
          return Response.json({ ok: false, reason: "refused_smaller" }, { status: 409 });
        }
        const { error } = await v.db
          .from("guild_settings")
          .upsert({ guild_id: BACKUP_ROW, settings: { ...parsed.data, at: new Date().toISOString() } as never, updated_at: new Date().toISOString() });
        if (error) return new Response("Backup failed", { status: 503 });
        return Response.json({ ok: true });
      },
    },
  },
});
