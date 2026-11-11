// Last status the PEAK bot reported (kept in memory; the bot re-sends it every few minutes).
export type BotStatusCode =
  | "starting"
  | "no_token"
  | "bad_token"
  | "intents"
  | "rate_limited"
  | "network"
  | "error"
  | "online";

let last: { code: BotStatusCode; detail: string; at: string } | null = null;

export function setBotStatus(code: BotStatusCode, detail = "") {
  last = { code, detail: detail.slice(0, 300), at: new Date().toISOString() };
}

export function getBotStatus() {
  return last;
}
