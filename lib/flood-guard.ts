// Stops one address from flooding the site with requests (an attempt to slow it down or take it offline).
// Each limiter counts requests per address in a sliding window; going over the limit blocks that
// address for a short time. Normal visitors and the bot never get close to these numbers.
export type Limiter = {
  hit: (key: string, now?: number) => { ok: boolean; retryAfter: number };
  blocked: (key: string, now?: number) => boolean;
  reset: () => void;
};

export function createLimiter(opts: { max: number; windowMs: number; blockMs: number }): Limiter {
  const map = new Map<string, { hits: number[]; blockedUntil: number }>();
  return {
    hit(key, now = Date.now()) {
      const e = map.get(key) ?? { hits: [], blockedUntil: 0 };
      if (e.blockedUntil > now) return { ok: false, retryAfter: Math.ceil((e.blockedUntil - now) / 1000) };
      e.hits = e.hits.filter((t) => now - t < opts.windowMs);
      e.hits.push(now);
      if (e.hits.length > opts.max) {
        e.blockedUntil = now + opts.blockMs;
        e.hits = [];
        map.set(key, e);
        return { ok: false, retryAfter: Math.ceil(opts.blockMs / 1000) };
      }
      map.set(key, e);
      if (map.size > 20000) {
        for (const [k, v] of map) if (v.blockedUntil < now && !v.hits.some((t) => now - t < opts.windowMs)) map.delete(k);
      }
      return { ok: true, retryAfter: 0 };
    },
    blocked: (key, now = Date.now()) => (map.get(key)?.blockedUntil ?? 0) > now,
    reset: () => map.clear(),
  };
}

/** Pages, pictures and site files: a page load needs a few dozen of these. */
export const pageLimiter = createLimiter({ max: 600, windowMs: 60_000, blockMs: 60_000 });
/** Dashboard actions and sign-in (each one does real work on the server). */
export const actionLimiter = createLimiter({ max: 240, windowMs: 60_000, blockMs: 120_000 });
/** Wrong bot keys: someone guessing or hammering the bot's private address. */
export const botKeyFailLimiter = createLimiter({ max: 20, windowMs: 15 * 60_000, blockMs: 5 * 60_000 });

export const MAX_BODY_BYTES = 8 * 1024 * 1024;
export const MAX_BOT_BODY_BYTES = 10 * 1024 * 1024;

export function isBotPath(pathname: string) {
  return pathname.startsWith("/api/public/bot/");
}

export function isActionPath(pathname: string) {
  return pathname.startsWith("/_serverFn") || pathname.startsWith("/api/");
}

/** Returns a refusal when the request is too big or the address is flooding; otherwise null. */
export function floodCheck(request: Request, ip: string, now = Date.now()): Response | null {
  const { pathname } = new URL(request.url);
  const len = Number(request.headers.get("content-length") ?? "0");
  const bot = isBotPath(pathname);
  if (Number.isFinite(len) && len > (bot ? MAX_BOT_BODY_BYTES : MAX_BODY_BYTES)) {
    return new Response("Request is too large.", { status: 413, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  // The bot's own address has its private key check (and its wrong-key limiter) instead.
  if (bot) return null;
  const r = (isActionPath(pathname) ? actionLimiter : pageLimiter).hit(ip, now);
  if (r.ok) return null;
  return new Response("Too many requests. Please wait a moment and try again.", {
    status: 429,
    headers: { "content-type": "text/plain; charset=utf-8", "retry-after": String(r.retryAfter) },
  });
}
