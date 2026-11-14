import { afterEach, describe, expect, it } from "vitest";
import { decryptText, encryptText, isEncrypted, tryDecrypt } from "./crypto.server";
import { LOCK_MS, MAX_FAILS, isLocked, noteFail, noteSuccess, resetLoginGuard } from "./login-guard.server";
import { withSecurityHeaders } from "./security-headers";

process.env["SESSION_SECRET"] = "test-secret-0123456789abcdef0123456789abcdef";

describe("stored secrets are encrypted", () => {
  afterEach(() => {
    delete process.env["DATA_ENCRYPTION_KEY"];
  });

  it("never stores the bot token as readable text and reads it back exactly", () => {
    const token = "MTU2OTMyMzI4MDUyMTc2NDk2NQ.abc.def";
    const stored = encryptText(token);
    expect(isEncrypted(stored)).toBe(true);
    expect(stored).not.toContain(token);
    expect(decryptText(stored)).toBe(token);
  });

  it("rejects a stored value that was changed", () => {
    const stored = encryptText("secret");
    const bad = stored.slice(0, -4) + (stored.endsWith("AAAA") ? "BBBB" : "AAAA");
    expect(tryDecrypt(bad)).toBeNull();
  });

  it("cannot be unlocked with a different server key", () => {
    const stored = encryptText("secret");
    process.env["DATA_ENCRYPTION_KEY"] = "another-key";
    expect(tryDecrypt(stored)).toBeNull();
  });

  it("still reads older plain values saved before encryption", () => {
    expect(tryDecrypt("plain-old-token")).toBe("plain-old-token");
  });
});

describe("admin sign-in lockout", () => {
  afterEach(() => resetLoginGuard());

  it("locks after 5 wrong tries for 15 minutes", () => {
    expect(MAX_FAILS).toBe(5);
    expect(LOCK_MS).toBe(15 * 60_000);
    const t = 1_000_000;
    for (let i = 0; i < 4; i++) noteFail("1.2.3.4", t + i);
    expect(isLocked("1.2.3.4", t + 5)).toBe(false);
    noteFail("1.2.3.4", t + 5);
    expect(isLocked("1.2.3.4", t + 6)).toBe(true);
    expect(isLocked("5.6.7.8", t + 6)).toBe(false);
    expect(isLocked("1.2.3.4", t + 5 + 15 * 60_000 + 1)).toBe(false);
  });

  it("a correct sign-in clears the wrong tries", () => {
    for (let i = 0; i < 4; i++) noteFail("9.9.9.9");
    noteSuccess("9.9.9.9");
    noteFail("9.9.9.9");
    expect(isLocked("9.9.9.9")).toBe(false);
  });
});

describe("protective headers", () => {
  it("adds HTTPS-only and anti-framing headers and keeps the page content", async () => {
    const res = withSecurityHeaders(new Request("https://district99.net/"), new Response("hi", { status: 200 }));
    expect(res.headers.get("strict-transport-security")).toContain("max-age=31536000");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("content-security-policy")).toContain("frame-ancestors 'self'");
    expect(await res.text()).toBe("hi");
  });

  it("never lets private answers be cached", () => {
    const res = withSecurityHeaders(new Request("https://district99.net/api/public/bot/sync"), Response.json({ token: "x" }));
    expect(res.headers.get("cache-control")).toBe("no-store");
    const page = withSecurityHeaders(new Request("https://district99.net/"), new Response("hi"));
    expect(page.headers.get("cache-control")).toBeNull();
  });

  it("keeps redirects working", () => {
    const res = withSecurityHeaders(new Request("https://district99.net/api/auth/discord/login"), Response.redirect("https://discord.com/x", 302));
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("https://discord.com/x");
  });
});
