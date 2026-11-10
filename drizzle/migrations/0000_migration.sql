CREATE TABLE public.bot_config (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  client_id text, client_secret text, bot_token text,
  sync_key text NOT NULL DEFAULT encode(gen_random_bytes(24),'hex'),
  last_bot_ping timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.bot_config TO service_role;
ALTER TABLE public.bot_config ENABLE ROW LEVEL SECURITY;
INSERT INTO public.bot_config (id) VALUES (1);

CREATE TABLE public.guild_settings (
  guild_id text PRIMARY KEY,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.guild_settings TO service_role;
ALTER TABLE public.guild_settings ENABLE ROW LEVEL SECURITY;

CREATE TABLE public.bot_stats (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  servers int NOT NULL DEFAULT 0, users int NOT NULL DEFAULT 0, active_tickets int NOT NULL DEFAULT 0,
  guild_ids text[] NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.bot_stats TO service_role;
ALTER TABLE public.bot_stats ENABLE ROW LEVEL SECURITY;
INSERT INTO public.bot_stats (id) VALUES (1);