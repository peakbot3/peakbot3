# PEAK bot (Python)

1. Discord Developer Portal → your application:
   - **Bot** tab: enable *Server Members Intent* and *Message Content Intent*.
   - **OAuth2 → Redirects**: add the Redirect URL shown in the PEAK admin panel.
2. On the website, tap the PEAK logo 5 times → sign in → paste Client ID, Client Secret and Bot Token → Save.
3. Copy `SITE_URL` and `SYNC_KEY` from the admin panel into `bot/.env` (see `.env.example`).
4. Run (Python 3.10+, on a VPS / Railway / any always-on host):

```bash
pip install -r requirements.txt
python peak_bot.py
```

The bot re-reads settings from the website every 30 seconds, so changes in the dashboard apply automatically.

## Discord rules compliance
- Uses the official bot API only (no self-bot), respects rate limits (discord.py queues by Discord headers) plus extra delays on bulk actions (auto roles, rewards, auto line cooldown ≥ 2s).
- Website login only asks for `identify guilds` scopes, uses a `state` check and a short cooldown between authorize attempts.
- Never pings @everyone/roles from user content; DMs are only sent for welcome DM (opt-in) and application results.
- Data stored: settings, XP, warnings and open tickets only.
