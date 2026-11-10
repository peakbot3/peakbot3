import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("@/integrations/supabase/client.server", () => ({
  supabaseAdmin: {
    from: () => {
      throw new Error("no db in tests");
    },
  },
}));
import { dfetch, discordPausedUntil, guildBasics } from "./discord.server";
import { putSnapshots, resetGuildCache, setBotGuildIds } from "./guild-cache.server";

const snap = {
  id: "111111111111111111",
  name: "Test",
  icon: null,
  member_count: 7,
  channels: [
    { id: "222222222222222222", name: "b", type: 0, parent_id: null, position: 2 },
    { id: "333333333333333333", name: "a", type: 0, parent_id: null, position: 1 },
  ],
  roles: [
    { id: "111111111111111111", name: "@everyone", color: 0, position: 0, managed: false },
    { id: "444444444444444444", name: "Mod", color: 1, position: 1, managed: false },
  ],
};

afterEach(() => {
  resetGuildCache();
  vi.unstubAllGlobals();
  delete process.env["DISCORD_BOT_TOKEN"];
});

describe("dashboard server info without Discord calls", () => {
  it("uses the bot's server info and never calls Discord", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setBotGuildIds([snap.id]);
    putSnapshots([snap]);
    const r = await guildBasics(snap.id);
    expect(fetchMock).not.toHaveBeenCalled();
    if (r.botMissing) throw new Error("expected server");
    expect(r.channels.map((c) => c.name)).toEqual(["a", "b"]);
    expect(r.roles.map((r) => r.name)).toEqual(["Mod"]);
    expect(r.guild.memberCount).toBe(7);
  });

  it("knows the bot is missing from a server without calling Discord", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setBotGuildIds([snap.id]);
    expect(await guildBasics("999999999999999999")).toEqual({ botMissing: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back to Discord once for many tabs at the same time, then caches", async () => {
    process.env["DISCORD_BOT_TOKEN"] = "x.y.z";
    const fetchMock = vi.fn(async (url: string) => {
      const body = url.includes("/channels") ? [] : url.includes("/roles") ? [] : { id: "555555555555555555", name: "G", icon: null };
      return new Response(JSON.stringify(body), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    await Promise.all(Array.from({ length: 10 }, () => guildBasics("555555555555555555")));
    await guildBasics("555555555555555555");
    expect(fetchMock).toHaveBeenCalledTimes(3); // server + channels + roles, once
  });

  it("a normal Discord 429 does not pause the whole site for 30 minutes", async () => {
    let n = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        n++ === 0
          ? new Response(JSON.stringify({ message: "You are being rate limited.", retry_after: 0.1, global: false }), { status: 429 })
          : new Response("{}", { status: 200 }),
      ),
    );
    const r = await dfetch("/users/@me/guilds", { headers: { Authorization: "Bearer abc" } });
    expect(r.status).toBe(200);
    expect(discordPausedUntil()).toBe(0);
  });
});
