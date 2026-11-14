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

## Security
- HTTPS only (HSTS), protective browser headers on every page, private answers never cached.
- Bot Token, Client Secret, every server's settings and the bot's data backup are encrypted (AES-256-GCM) in the database.
- Flood protection: one address is blocked for a short time after too many requests (600 pages or 240 dashboard actions per minute), requests over 8 MB are refused, and wrong bot keys lock that address for 5 minutes after 20 tries.
- Against big attacks from many addresses (DDoS), put the domain behind Cloudflare (free plan, orange cloud on).
- Sign-in sessions are sealed, HttpOnly + Secure cookies. Admin sign-in locks for 15 minutes after 5 wrong tries.
- Database tables are closed to public keys (Row Level Security + `REVOKE` in `supabase/setup.sql`; re-run it once).
- Optional env var `DATA_ENCRYPTION_KEY`: set it once and never change it (otherwise save the bot details again in the admin panel).
