import { describe, expect, it } from "vitest";
import { GAMES, deepMerge, defaultSettings } from "./settings";

describe("new options are off until the server turns them on", () => {
  it("ticket DM on close and add-member buttons start disabled", () => {
    const s = defaultSettings();
    expect(s.tickets.dmOnClose.enabled).toBe(false);
    expect(s.tickets.addMember.enabled).toBe(false);
    expect(s.games.enabled).toBe(false);
    expect(s.bank.enabled).toBe(false);
  });

  it("old saved settings keep their values and gain the new sections", () => {
    const saved = { tickets: { enabled: true, transcripts: false }, general: { prefix: "#" } };
    const s = deepMerge(defaultSettings(), saved);
    expect(s.tickets.enabled).toBe(true);
    expect(s.tickets.transcripts).toBe(false);
    expect(s.general.prefix).toBe("#");
    expect(s.tickets.dmOnClose.sendTranscript).toBe(true);
    expect(s.bank.transferTax).toBe(5);
  });

  it("every game fits in one Discord menu", () => {
    expect(GAMES.length).toBeLessThanOrEqual(25);
    expect(Object.keys(defaultSettings().games.list)).toHaveLength(GAMES.length);
  });
});
