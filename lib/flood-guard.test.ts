import { afterEach, describe, expect, it } from "vitest";
import { actionLimiter, botKeyFailLimiter, createLimiter, floodCheck, pageLimiter } from "./flood-guard";
import { openSettings, sealSettings } from "./settings-store.server";

process.env["SESSION_SECRET"] = "test-secret-0123456789abcdef0123456789abcdef";

describe("flood protection", () => {
  afterEach(() => {
    pageLimiter.reset();
    actionLimiter.reset();
    botKeyFailLimiter.reset();
  });

  it("blocks an address that goes over the limit, then lets it back in after the block", () => {
    const l = createLimiter({ max: 3, windowMs: 60_000, blockMs: 60_000 });
    const t = 1_000_000;
    expect([1, 2, 3].map((i) => l.hit("a", t + i).ok)).toEqual([true, true, true]);
    expect(l.hit("a", t + 4).ok).toBe(false);
    expect(l.hit("b", t + 4).ok).toBe(true);
    expect(l.hit("a", t + 61_000).ok).toBe(true);
  });

  it("answers 429 after 240 dashboard actions in a minute from one address", () => {
    const req = () => new Request("https://district99.net/_serverFn/x", { method: "POST" });
    const t = 5_000_000;
    for (let i = 0; i < 240; i++) expect(floodCheck(req(), "1.2.3.4", t + i)).toBeNull();
    expect(floodCheck(req(), "1.2.3.4", t + 241)?.status).toBe(429);
  });

  it("never rate-limits the bot's own address by request count", () => {
    const req = new Request("https://district99.net/api/public/bot/sync");
    for (let i = 0; i < 1000; i++) expect(floodCheck(req, "9.9.9.9", 7_000_000 + i)).toBeNull();
  });

  it("refuses requests bigger than 8 MB", () => {
    const req = new Request("https://district99.net/_serverFn/x", { method: "POST", headers: { "content-length": String(9 * 1024 * 1024) } });
    expect(floodCheck(req, "1.1.1.1")?.status).toBe(413);
  });
});

describe("server settings are stored encrypted", () => {
  it("hides the settings and reads them back exactly", () => {
    const s = { welcome: { enabled: true, message: "Hello {user}" } };
    const sealed = sealSettings(s);
    expect(JSON.stringify(sealed)).not.toContain("Hello");
    expect(openSettings(sealed)).toEqual(s);
  });

  it("still reads settings saved before encryption", () => {
    expect(openSettings({ welcome: { enabled: false } })).toEqual({ welcome: { enabled: false } });
  });

  it("returns nothing when the settings cannot be unlocked", () => {
    expect(openSettings({ __enc: "enc:v1:AAAA" })).toBeNull();
  });
});
