// The PEAK bot keeps XP, bank, warnings and tickets in a local file. A copy is stored on the website in
// this guild_settings row so the data survives the bot's host wiping its files (e.g. a redeploy).
// The id is not a number, so it can never collide with a Discord server id.
export const BACKUP_ROW = "peak_backup";
export const MAX_BACKUP_CHARS = 8_000_000;
