import { useSession } from "@tanstack/react-start/server";
import { createHash } from "node:crypto";

export type DiscordUser = { id: string; username: string; global_name: string | null; avatar: string | null };
export type AppSession = {
  user?: DiscordUser;
  accessToken?: string;
  admin?: boolean;
  oauthState?: string | undefined;
  lastAuthAt?: number;
  manageable?: string[];
};

/** SESSION_SECRET when set; otherwise a stable key derived from other server-only secrets. */
function sessionPassword() {
  const explicit = (process.env["SESSION_SECRET"] ?? "").trim();
  if (explicit.length >= 32) return explicit;
  const base = explicit + (process.env["SUPABASE_SERVICE_ROLE_KEY"] ?? "") + (process.env["ADMIN_PASSWORD"] ?? "");
  if (!base) throw new Error("SESSION_SECRET is not set");
  return createHash("sha256").update(`peak-session:${base}`).digest("hex");
}

export function getAppSession() {
  return useSession<AppSession>({
    password: sessionPassword(),
    name: "peak-session",
    maxAge: 60 * 60 * 24 * 7,
    // "none" so the session also works inside the editor preview frame.
    cookie: { httpOnly: true, secure: true, sameSite: "none", path: "/" },
  });
}
