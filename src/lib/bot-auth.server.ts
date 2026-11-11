import { createHash, timingSafeEqual } from "node:crypto";

// Checks the "Authorization: Bearer <sync key>" header the PEAK Python bot sends.
export async function verifyBot(request: Request) {
  const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
  const { getBotConfig } = await import("@/lib/discord.server");
  const cfg = await getBotConfig();
  const given = (request.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const h = (v: string) => createHash("sha256").update(v).digest();
  const ok = !!cfg.sync_key && given.length > 0 && timingSafeEqual(h(given), h(cfg.sync_key));
  return ok ? { db: supabaseAdmin, cfg } : null;
}
