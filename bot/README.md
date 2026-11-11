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

## Games, bank and tickets (all off until you turn them on in the dashboard)
- **Games** tab: `/play` or the games prefix (default `-`): `-روليت` `-مافيا` `-كراسي` `-حجرة` `-نرد` `-عجلة` `-قنبلة` `-اكس @user` `-نار @user`,
  quick games `-اسرع` `-اعكس` `-فكك` `-ركب` `-اعلام` `-عواصم` `-حساب` `-رتب` `-ايموجي`. Stop with `-ايقاف` or `/stop`.
- **Bank** tab: with the bot prefix: `رصيد` `يومي` `راتب` `تحويل @user 100` `ايداع 100` `سحب 100` `نهب @user` `قمار 100` `سلوت 100`
  `وجه 100` `الاغنى` `اعطاء @user 100` (admins) `بنك` (buttons menu). Slash: `/balance` `/daily` `/work` `/transfer` `/bank` `/rich`.
- **Tickets** tab: "Message to the member when a ticket closes" (DM card + transcript file) and "Add people to a ticket" buttons.

## Your data is kept
XP, bank money, warnings and open tickets are stored in `peak.db` (or the path in `DB_PATH`). A compressed copy is sent to
the website every 5 minutes, and a fresh host with an empty `peak.db` restores it automatically on start.

## Discord rules compliance
- Uses the official bot API only (no self-bot), respects rate limits (discord.py queues by Discord headers) plus extra delays on bulk actions (auto roles, rewards, auto line cooldown ≥ 2s).
- Website login only asks for `identify guilds` scopes, uses a `state` check and a short cooldown between authorize attempts.
- Never pings @everyone/roles from user content; DMs are only sent for welcome DM (opt-in), application results and the ticket-close summary (opt-in).
- Games: one game per channel, at most 3 big games per server, pauses between rounds, button clicks answered through the click itself (no extra API calls).
- Data stored: settings, XP, warnings, open tickets, bank balances and game wins only.
