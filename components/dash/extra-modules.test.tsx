import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { DashCtx } from "./fields";
import { defaultSettings } from "@/lib/settings";

vi.mock("@tanstack/react-start", () => ({ useServerFn: () => async () => ({}) }));
vi.mock("@/lib/api.functions", () => ({ sendReactionRolePanel: {}, sendToChannel: {}, setBotServerAvatar: {} }));

const { AutoReactModule, AutoReplyModule, BotProfileModule, ModDmModule, ReactionRolesModule, TempVoiceModule } = await import("./extra-modules");

function wrap(ui: React.ReactNode, s = defaultSettings()) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DashCtx.Provider value={{ s, set: () => {}, channels: [{ id: "1", name: "general", type: 0, parentId: null }], roles: [{ id: "2", name: "VIP", color: 0, managed: false }], emojis: [], guild: { id: "9", name: "Test", icon: null, memberCount: 5 } }}>
        {ui}
      </DashCtx.Provider>
    </QueryClientProvider>,
  );
}

describe("new dashboard pages open without errors", () => {
  it("temp voice shows the 15 panel buttons", () => {
    wrap(<TempVoiceModule />);
    expect(screen.getAllByTitle(/^(Name|Limit|Privacy|Waiting room|Chat|Trust|Untrust|Invite|Kick|Region|Block|Unblock|Delete|Claim|Transfer)$/)).toHaveLength(15);
  });

  it("emoji roles, auto emoji, auto reply, punishment DMs and bot profile render", () => {
    const s = defaultSettings();
    s.reactionRoles.panels = [{ id: "p", channelId: "1", messageId: "", mode: "buttons", unique: true, embed: s.rules.embeds[0]!, items: [{ emoji: "🔥", roleId: "2", label: "" }] }];
    s.autoReply.replies = [{ id: "r", triggers: ["hi"], match: "exact", response: "hello", asReply: true, asEmbed: false, channels: [], enabled: true }];
    for (const C of [ReactionRolesModule, AutoReactModule, AutoReplyModule, ModDmModule, BotProfileModule]) {
      const { unmount } = wrap(<C />, s);
      unmount();
    }
    expect(true).toBe(true);
  });
});
