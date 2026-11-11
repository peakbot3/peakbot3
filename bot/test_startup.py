"""Isolated startup regressions: no Discord login, database or real secrets."""
import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name("peak_bot.py")


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def run_startup(self, env, site_available):
        tree = ast.parse(SOURCE.read_text())
        main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
        calls = []

        async def fetch():
            calls.append("site")
            if not site_available:
                raise AssertionError("Startup must not wait for the site with a host token")
            return {"token": "test-site-token", "guilds": []}

        async def start(token):
            calls.append(("login", token))

        async def noop(*args):
            pass

        tasks = []
        def task(coro):
            t = asyncio.create_task(coro)
            tasks.append(t)
            return t

        scope = {
            "os": os, "aiohttp": SimpleNamespace(ClientSession=lambda: object()),
            "asyncio": SimpleNamespace(create_task=task), "health_server": noop, "restore_backup": noop,
            "fetch_site_config": fetch, "report": noop, "SETTINGS": {},
            "sync_loop": noop, "client": SimpleNamespace(start=start),
        }
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), "exec"), scope)
        with patch.dict(os.environ, env, clear=True):
            await scope["main"]()
            await asyncio.gather(*tasks)
        return calls

    async def test_render_discord_token_starts_without_website(self):
        self.assertEqual(await self.run_startup({"DISCORD_BOT_TOKEN": "test-render-token"}, False), [("login", "test-render-token")])

    async def test_existing_bot_token_starts_without_website(self):
        self.assertEqual(await self.run_startup({"BOT_TOKEN": "test-existing-token"}, False), [("login", "test-existing-token")])

    async def test_website_token_fallback_preserved(self):
        self.assertEqual(await self.run_startup({}, True), ["site", ("login", "test-site-token")])


if __name__ == "__main__":
    unittest.main()