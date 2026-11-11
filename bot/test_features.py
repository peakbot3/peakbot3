"""Feature checks for tickets, bank, games and backup. No Discord login, no network."""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("SITE_URL", "http://localhost")
os.environ.setdefault("SYNC_KEY", "test")
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
import peak_bot as pb  # noqa: E402


def member(uid, name="user", bot=False, roles=()):
    return SimpleNamespace(
        id=uid, name=name, display_name=name, mention=f"<@{uid}>", bot=bot, roles=list(roles),
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/embed/avatars/0.png"),
        guild_permissions=SimpleNamespace(administrator=False, manage_guild=False),
        guild=None,
    )


GUILD = SimpleNamespace(id=111, name="Test", icon=None, get_role=lambda rid: SimpleNamespace(name="Support") if rid == 5 else None)
SET = {"general": {"language": "en", "embedColor": "#22d3ee"}, "bank": {"enabled": True, "dailyAmount": 500, "transferTax": 5, "startBalance": 0, "currencyEmoji": "🪙", "rob": {"enabled": True}, "gamble": {"enabled": True, "maxBet": 1000}}}


class BankTests(unittest.TestCase):
    def setUp(self):
        pb.db.execute("DELETE FROM bank")
        pb.db.execute("DELETE FROM bank_cool")
        pb.db.commit()

    def test_daily_gives_amount_once_per_day(self):
        a = member(1)
        pb.act_daily(GUILD, a, SET)
        self.assertEqual(pb.account("111", "1", SET), (500, 0))
        pb.act_daily(GUILD, a, SET)  # second time the same day: nothing
        self.assertEqual(pb.account("111", "1", SET), (500, 0))

    def test_transfer_takes_five_percent_tax(self):
        a, b = member(1), member(2)
        pb.bank_add("111", "1", SET, wallet=1000)
        err, amt, tax = pb.check_transfer(GUILD, a, b, SET, "100")
        self.assertIsNone(err)
        self.assertEqual((amt, tax), (100, 5))
        pb.do_transfer(GUILD, a, b, SET, amt, tax)
        self.assertEqual(pb.account("111", "1", SET)[0], 900)
        self.assertEqual(pb.account("111", "2", SET)[0], 95)

    def test_cannot_send_more_than_wallet(self):
        pb.bank_add("111", "1", SET, wallet=50)
        err, _, _ = pb.check_transfer(GUILD, member(1), member(2), SET, "100")
        self.assertIsNotNone(err)
        self.assertEqual(pb.account("111", "1", SET)[0], 50)

    def test_deposit_and_withdraw_all(self):
        pb.bank_add("111", "1", SET, wallet=300)
        pb.act_move(GUILD, member(1), SET, "all", True)
        self.assertEqual(pb.account("111", "1", SET), (0, 300))
        pb.act_move(GUILD, member(1), SET, "half", False)
        self.assertEqual(pb.account("111", "1", SET), (150, 150))

    def test_bet_above_max_is_refused(self):
        pb.bank_add("111", "1", SET, wallet=5000)
        pb.act_bet(GUILD, member(1), SET, "2000")
        self.assertEqual(pb.account("111", "1", SET)[0], 5000)

    def test_amount_parsing(self):
        self.assertEqual(pb.parse_amount("1k", 0), 1000)
        self.assertEqual(pb.parse_amount("كل", 77), 77)
        self.assertIsNone(pb.parse_amount("abc", 10))


class TicketDmTests(unittest.TestCase):
    def test_dm_card_has_number_staff_claim_and_file(self):
        s = {"general": {"language": "ar"}, "tickets": {"supportRoles": ["5"], "categories": [], "dmOnClose": {"enabled": True, "message": ""}}}
        row = ("9", "support", "42", 1_700_000_000, 312)
        em, em2 = pb.ticket_dm_embeds(GUILD, s, row, False, True, "transcript-ticket-x.txt")
        fields = {f.name: f.value for f in em.fields}
        self.assertEqual(fields["📄 : رقم التذكرة"], "`312`")
        self.assertEqual(fields["👑 : مشرفين التذكرة"], "@Support")
        self.assertEqual(fields["🛡️ : مسؤول التذكرة"], "<@42>")
        self.assertIn("📁 : ملف التذكرة", fields)
        self.assertIn("تم قفل تذكرتك من قبل الإدارة", em2.description)

    def test_unclaimed_ticket_without_file(self):
        s = {"general": {"language": "en"}, "tickets": {"supportRoles": [], "categories": []}}
        em, _ = pb.ticket_dm_embeds(GUILD, s, ("9", "x", None, 1_700_000_000, 3), True, False, "f.txt")
        fields = {f.name: f.value for f in em.fields}
        self.assertEqual(fields["🛡️ : Claimed by"], "Nobody claimed the ticket")
        self.assertNotIn("📁 : Ticket file", fields)

    def test_ticket_numbers_go_up_per_server(self):
        self.assertEqual(pb.next_ticket_num("555") + 1, pb.next_ticket_num("555"))


class GamesTests(unittest.TestCase):
    def test_every_mini_game_accepts_its_own_answer(self):
        for gid, info in pb.GAME_INFO.items():
            if info[3] != "mini":
                continue
            for lang in ("en", "ar"):
                text, answers, loose = pb.make_question(gid, {"general": {"language": lang}})
                key = pb.canon if loose else pb.norm
                self.assertTrue(text and answers, gid)
                self.assertIn(key(answers[0]), {key(a) for a in answers})

    def test_copied_fast_word_is_rejected(self):
        text, answers, _ = pb.make_question("fast", {"general": {"language": "en"}})
        shown = text.split("# ", 1)[1]
        self.assertNotEqual(shown, answers[0])
        self.assertTrue(pb.ZW_RE.search(shown))

    def test_arabic_commands_find_games(self):
        self.assertEqual(pb.GAME_WORDS[pb.norm("روليت")], "roulette")
        self.assertEqual(pb.GAME_WORDS[pb.norm("مافيا")], "mafia")
        self.assertEqual(pb.GAME_WORDS[pb.norm("اكس")], "xo")
        self.assertEqual(pb.GAME_WORDS[pb.norm("حجرةورقةمقص")], "rps")

    def test_wheel_image(self):
        f = pb.wheel_image([str(i) for i in range(1, 13)], 4)
        self.assertEqual(f.filename, "wheel.png")

    def test_slash_commands_are_valid(self):
        names = {c.name for c in pb.tree.get_commands()}
        self.assertTrue({"play", "stop", "balance", "daily", "transfer", "bank", "rank", "top"} <= names)
        self.assertEqual(len(pb._commands_signature()), 64)

    def test_views_build(self):
        async def go():
            s = {"general": {"language": "ar"}, "games": {"enabled": True}}
            ch = SimpleNamespace(id=1, guild=SimpleNamespace(id=2))
            game = pb.Roulette(ch, member(1), s, "roulette")
            ps = [member(i, f"p{i}") for i in range(1, 24)]
            self.assertLessEqual(len(pb.PickView(game, ps[0], ps[1:], extras=(("random", "r", "🎲"),)).children), 25)
            self.assertEqual(len(pb.ChairsView(game, ps[:6]).children), 6)
            pb.TicketControls()
            pb.bank_menu_view(s)
        asyncio.run(go())


class BackupTests(unittest.TestCase):
    def test_backup_round_trip_restores_rows(self):
        pb.db.execute("INSERT OR REPLACE INTO xp VALUES ('1','2',10,3)")
        pb.bank_add("1", "2", SET, wallet=777)
        pb.db.commit()
        data, h, rows = pb.dump_db()
        self.assertEqual(len(h), 64)
        self.assertGreater(rows, 0)
        pb.db.execute("DELETE FROM xp")
        pb.db.execute("DELETE FROM bank")
        pb.db.commit()
        pb.load_db(data)
        self.assertEqual(pb.db.execute("SELECT level FROM xp WHERE guild='1' AND user='2'").fetchone()[0], 3)
        self.assertEqual(pb.account("1", "2", SET)[0], 777)


if __name__ == "__main__":
    unittest.main()
