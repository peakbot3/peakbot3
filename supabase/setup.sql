-- PEAK website: one-time database setup.
-- Run this ONCE in the Supabase dashboard → SQL Editor of the project whose URL is in
-- your Render env var SUPABASE_URL. Safe to run again (it skips what already exists).

CREATE TABLE IF NOT EXISTS public.bot_config (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  client_id text,
  client_secret text,
  bot_token text,
  sync_key text NOT NULL DEFAULT (replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '')),
  last_bot_ping timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.bot_config TO service_role;
ALTER TABLE public.bot_config ENABLE ROW LEVEL SECURITY;
-- Application ID is public; the Client Secret and Bot Token are added from the admin panel.
INSERT INTO public.bot_config (id, client_id) VALUES (1, '1569323280521764965')
ON CONFLICT (id) DO UPDATE SET client_id = COALESCE(public.bot_config.client_id, EXCLUDED.client_id);

CREATE TABLE IF NOT EXISTS public.guild_settings (
  guild_id text PRIMARY KEY,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.guild_settings TO service_role;
ALTER TABLE public.guild_settings ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.bot_stats (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  servers int NOT NULL DEFAULT 0,
  users int NOT NULL DEFAULT 0,
  active_tickets int NOT NULL DEFAULT 0,
  guild_ids text[] NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.bot_stats TO service_role;
ALTER TABLE public.bot_stats ENABLE ROW LEVEL SECURITY;
INSERT INTO public.bot_stats (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Make the API see the new tables right away.
NOTIFY pgrst, 'reload schema';
