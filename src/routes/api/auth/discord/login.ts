import { createFileRoute } from "@tanstack/react-router";
import { randomBytes } from "node:crypto";
import { getBotConfig, redirectTo, siteOrigin } from "@/lib/discord.server";
import { getAppSession } from "@/lib/session.server";

export const Route = createFileRoute("/api/auth/discord/login")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        let cfg;
        try {
          cfg = await getBotConfig();
        } catch (e) {
          return new Response((e as Error).message, { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
        }
        if (!cfg.client_id || !cfg.client_secret) {
          return new Response("The bot is not set up yet. The site owner must add the bot details first.", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          });
        }
        const s = await getAppSession();
        // Small cooldown between authorize attempts to avoid hammering Discord's OAuth.
        const now = Date.now();
        if (s.data.lastAuthAt && now - s.data.lastAuthAt < 3000) {
          await new Promise((r) => setTimeout(r, 3000 - (now - s.data.lastAuthAt!)));
        }
        const state = randomBytes(16).toString("hex");
        await s.update({ oauthState: state, lastAuthAt: Date.now() });
        const params = new URLSearchParams({
          client_id: cfg.client_id,
          response_type: "code",
          redirect_uri: `${siteOrigin(request)}/api/auth/discord/callback`,
          scope: "identify guilds",
          state,
          prompt: "none",
        });
        return redirectTo(`https://discord.com/oauth2/authorize?${params}`);
      },
    },
  },
});
