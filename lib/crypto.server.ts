import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

// Encrypts secrets before they are saved in the database (bot token, client secret, bot data backup).
// AES-256-GCM: anyone who reads the database without the server key sees only random text,
// and any change to the stored text is detected when it is read back.
const PREFIX = "enc:v1:";

/** DATA_ENCRYPTION_KEY when set; otherwise derived from the same server-only secrets as the session key. */
function keyMaterial() {
  const explicit = (process.env["DATA_ENCRYPTION_KEY"] ?? "").trim();
  if (explicit) return `data-key:${explicit}`;
  const base =
    (process.env["SESSION_SECRET"] ?? "").trim() + (process.env["SUPABASE_SERVICE_ROLE_KEY"] ?? "") + (process.env["ADMIN_PASSWORD"] ?? "");
  if (!base) throw new Error("No server secret is set (DATA_ENCRYPTION_KEY or SESSION_SECRET).");
  return `peak-data:${base}`;
}

function key() {
  return createHash("sha256").update(keyMaterial()).digest();
}

export function isEncrypted(v: unknown): v is string {
  return typeof v === "string" && v.startsWith(PREFIX);
}

export function encryptText(plain: string): string {
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", key(), iv);
  const body = Buffer.concat([c.update(plain, "utf8"), c.final()]);
  return PREFIX + Buffer.concat([iv, c.getAuthTag(), body]).toString("base64");
}

/** Plain (older, not yet encrypted) values are returned as they are. Throws when the text was changed or the key is different. */
export function decryptText(stored: string): string {
  if (!isEncrypted(stored)) return stored;
  const raw = Buffer.from(stored.slice(PREFIX.length), "base64");
  if (raw.length < 28) throw new Error("Encrypted value is damaged.");
  const d = createDecipheriv("aes-256-gcm", key(), raw.subarray(0, 12));
  d.setAuthTag(raw.subarray(12, 28));
  return Buffer.concat([d.update(raw.subarray(28)), d.final()]).toString("utf8");
}

/** Like decryptText but never throws: returns null when the value cannot be unlocked. */
export function tryDecrypt(stored: string | null | undefined): string | null {
  if (stored == null || stored === "") return stored ?? null;
  try {
    return decryptText(stored);
  } catch {
    return null;
  }
}
