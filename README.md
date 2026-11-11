# PEAK — Discord Bot & Dashboard

Website (TanStack Start + React + Tailwind) and Python bot (`/bot`, discord.py).

## Website
```sh
npm i
npm run dev
```
Set env vars from `.env.example` style: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SESSION_SECRET`, `ADMIN_PASSWORD`.

## Bot
See `bot/README.md`.

## Discord compliance
- Official bot API only, honours rate limits (429 Retry-After) with extra delays on bulk actions.
- OAuth scopes limited to `identify guilds`, `state` check, cooldown between authorize attempts.
- No mass pings from user content; DMs only opt-in (welcome DM, ticket-close summary).
- Never commit your bot token / client secret — they are stored in the admin panel, not in code.

## Render setup (district99.net)
1. Supabase dashboard → SQL Editor → run `supabase/setup.sql` once (creates the tables the admin panel needs).
2. Render → Environment: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_PUBLISHABLE_KEY`, `SESSION_SECRET`, `ADMIN_PASSWORD`, and `SITE_URL=https://district99.net`.
3. Discord Developer Portal → OAuth2 → Redirects: `https://district99.net/api/auth/discord/callback`.
4. The Python bot (`/bot`) must run on an always-on host (e.g. a Render Background Worker) with `SITE_URL` and `SYNC_KEY`.
