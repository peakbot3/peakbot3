import { createFileRoute } from "@tanstack/react-router";
import { dfetch, getBotConfig, redirectTo, siteOrigin } from "@/lib/discord.server";
import { getAppSession, type DiscordUser } from "@/lib/session.server";
import { ADMIN_DISCORD_ID } from "@/lib/settings";

export const Route = createFileRoute("/api/auth/discord/callback")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const url = new URL(request.url);
        const origin = siteOrigin(request);
        const code = url.searchParams.get("code");
        const state = url.searchParams.get("state");
        const s = await getAppSession();
        if (!code || !state || state !== s.data.oauthState) {
          return redirectTo(`${origin}/dashboard?login=failed`);
        }
        const cfg = await getBotConfig();
        const tokenRes = await dfetch("/oauth2/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            client_id: cfg.client_id ?? "",
            client_secret: cfg.client_secret ?? "",
            grant_type: "authorization_code",
            code,
            redirect_uri: `${origin}/api/auth/discord/callback`,
          }),
        }).catch((e: Error) => {
          console.error("Discord token exchange skipped:", e.message);
          return null;
        });
        if (!tokenRes?.ok) {
          if (tokenRes) console.error("Discord token exchange failed", tokenRes.status, await tokenRes.text());
          return redirectTo(`${origin}/dashboard?login=failed`);
        }
        const tok = (await tokenRes.json()) as { access_token: string };
        const meRes = await dfetch("/users/@me", { headers: { Authorization: `Bearer ${tok.access_token}` } }).catch(() => null);
        if (!meRes?.ok) {
          if (meRes) console.error("Discord /users/@me failed", meRes.status, await meRes.text());
          return redirectTo(`${origin}/dashboard?login=failed`);
        }
        const me = (await meRes.json()) as DiscordUser;
        await s.update({
          user: { id: me.id, username: me.username, global_name: me.global_name, avatar: me.avatar },
          accessToken: tok.access_token,
          oauthState: undefined,
          manageable: [],
          admin: s.data.admin || me.id === ADMIN_DISCORD_ID,
        });
        return redirectTo(`${origin}/dashboard`);
      },
    },
  },
});
