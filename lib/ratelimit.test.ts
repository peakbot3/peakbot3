import { describe, expect, it, vi } from "vitest";
vi.mock("@/integrations/supabase/client.server", () => ({ supabaseAdmin: {} }));
import { appIdFromToken, dfetch, discordPausedUntil } from "./discord.server";

describe("Discord safety", () => {
  it("reads the application ID from a bot token", () => {
    const id = "1569323280521764965";
    const tok = `${btoa(id).replace(/=+$/, "")}.abc.def`;
    expect(appIdFromToken(tok)).toBe(id);
    expect(appIdFromToken("garbage")).toBeNull();
  });

  it("stops all Discord calls after an IP block instead of retrying", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ code: 0, message: "blocked" }), { status: 429, headers: { "retry-after": "60" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(dfetch("/users/@me")).rejects.toThrow(/paused/);
    expect(discordPausedUntil()).toBeGreaterThan(Date.now() + 29 * 60_000);
    await expect(dfetch("/users/@me")).rejects.toThrow(/paused/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
