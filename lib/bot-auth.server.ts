import { createHash, timingSafeEqual } from "node:crypto";

// Checks the "Authorization: Bearer <sync key>" header the PEAK Python bot sends.
export async function verifyBot(request: Request) {
  // Too many wrong keys from one address: refuse without even looking at the database.
  const { botKeyFailLimiter } = await import("@/lib/flood-guard");
  const { clientIp } = await import("@/lib/login-guard.server");
  const ip = clientIp(request);
  if (botKeyFailLimiter.blocked(ip)) return null;
  const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
  const { getBotConfig } = await import("@/lib/discord.server");
  const cfg = await getBotConfig();
  const given = (request.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const h = (v: string) => createHash("sha256").update(v).digest();
  const ok = !!cfg.sync_key && given.length > 0 && timingSafeEqual(h(given), h(cfg.sync_key));
  if (!ok) botKeyFailLimiter.hit(ip);
  return ok ? { db: supabaseAdmin, cfg } : null;
}
