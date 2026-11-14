import { encryptText, tryDecrypt } from "./crypto.server";

// Every server's settings are stored encrypted: the database only holds { __enc: "enc:v1:..." }.
// Settings saved before encryption are still read as they are and get encrypted on the next save.
type Settings = Record<string, unknown>;

export function isSealed(stored: unknown): stored is { __enc: string } {
  return !!stored && typeof stored === "object" && typeof (stored as { __enc?: unknown }).__enc === "string";
}

export function sealSettings(settings: Settings): { __enc: string } {
  return { __enc: encryptText(JSON.stringify(settings)) };
}

/** Returns the readable settings, or null when there are none or they cannot be unlocked (different key). */
export function openSettings(stored: unknown): Settings | null {
  if (stored == null) return null;
  if (!isSealed(stored)) return typeof stored === "object" ? (stored as Settings) : null;
  const plain = tryDecrypt(stored.__enc);
  if (plain == null) return null;
  try {
    const v = JSON.parse(plain) as unknown;
    return v && typeof v === "object" ? (v as Settings) : null;
  } catch {
    return null;
  }
}
