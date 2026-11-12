// Server info the PEAK bot already has in memory (from its Discord connection), pushed to the
// website. The dashboard reads channels / roles / server name from here instead of asking the
// Discord API on every page open — the same way big public bots run their dashboards.
// Kept in memory only: after a website restart the bot re-sends everything within ~2 minutes,
// and until then the dashboard falls back to a cached Discord API read.

export type SnapChannel = { id: string; name: string; type: number; parent_id: string | null; position: number };
export type SnapRole = { id: string; name: string; color: number; position: number; managed: boolean };
export type SnapEmoji = { id: string; name: string; animated: boolean };
export type GuildSnapshot = {
  id: string;
  name: string;
  icon: string | null;
  member_count: number;
  channels: SnapChannel[];
  roles: SnapRole[];
  /** Custom server emojis (older bots do not send them). */
  emojis?: SnapEmoji[] | undefined;
};

/** How long the bot's report is trusted without a new one (the bot reports every 2 minutes). */
export const BOT_REPORT_FRESH_MS = 6 * 60_000;

const snapshots = new Map<string, GuildSnapshot>();
let botIds = new Set<string>();
let lastReport = 0;

function fresh() {
  return lastReport > 0 && Date.now() - lastReport < BOT_REPORT_FRESH_MS;
}

/** Called when the bot reports the servers it is in (stats report or snapshot push). */
export function setBotGuildIds(ids: string[]) {
  botIds = new Set(ids);
  lastReport = Date.now();
  for (const id of snapshots.keys()) if (!botIds.has(id)) snapshots.delete(id);
}

export function putSnapshots(list: GuildSnapshot[], removed: string[] = []) {
  for (const g of list) snapshots.set(g.id, g);
  for (const id of removed) snapshots.delete(id);
  return snapshots.size;
}

export function snapshotCount() {
  return snapshots.size;
}

/** Servers the bot is in, or null when the bot has not reported recently. */
export function knownBotGuildIds(): Set<string> | null {
  return fresh() ? botIds : null;
}

export function getSnapshot(guildId: string): GuildSnapshot | null {
  return fresh() ? (snapshots.get(guildId) ?? null) : null;
}

/** Full bot server list (id, name, icon) when every server has a snapshot; otherwise null. */
export function snapshotGuildList(): { id: string; name: string; icon: string | null }[] | null {
  if (!fresh()) return null;
  const out: { id: string; name: string; icon: string | null }[] = [];
  for (const id of botIds) {
    const s = snapshots.get(id);
    if (!s) return null;
    out.push({ id: s.id, name: s.name, icon: s.icon });
  }
  return out;
}

/** Test helper. */
export function resetGuildCache() {
  snapshots.clear();
  botIds = new Set();
  lastReport = 0;
}
