// Stops password guessing on the admin sign-in: after MAX_FAILS wrong tries from one address
// within WINDOW_MS, that address is locked for LOCK_MS. A correct sign-in clears the count.
export const MAX_FAILS = 5;
export const WINDOW_MS = 15 * 60_000;
export const LOCK_MS = 15 * 60_000;

type Entry = { fails: number[]; lockedUntil: number };
const entries = new Map<string, Entry>();

export function clientIp(req: Request | undefined | null) {
  const h = req?.headers;
  const ip = h?.get("cf-connecting-ip") || h?.get("x-real-ip") || (h?.get("x-forwarded-for") ?? "").split(",")[0]?.trim();
  return ip || "unknown";
}

export function isLocked(ip: string, now = Date.now()) {
  const e = entries.get(ip);
  return !!e && e.lockedUntil > now;
}

export function noteFail(ip: string, now = Date.now()) {
  const e = entries.get(ip) ?? { fails: [], lockedUntil: 0 };
  e.fails = e.fails.filter((t) => now - t < WINDOW_MS);
  e.fails.push(now);
  if (e.fails.length >= MAX_FAILS) {
    e.lockedUntil = now + LOCK_MS;
    e.fails = [];
  }
  entries.set(ip, e);
  if (entries.size > 5000) {
    for (const [k, v] of entries) if (v.lockedUntil < now && !v.fails.some((t) => now - t < WINDOW_MS)) entries.delete(k);
  }
}

export function noteSuccess(ip: string) {
  entries.delete(ip);
}

export function resetLoginGuard() {
  entries.clear();
}
