// Shared (client-safe) guild settings shape + defaults. The Python bot reads the same JSON.
export const ADMIN_DISCORD_ID = "1418979814446075944";

export type Embed = {
  title: string;
  description: string;
  color: string;
  imageUrl: string;
  thumbnailUrl: string;
  footer: string;
  authorName: string;
};
export const emptyEmbed = (p: Partial<Embed> = {}): Embed => ({
  title: "",
  description: "",
  color: "#22d3ee",
  imageUrl: "",
  thumbnailUrl: "",
  footer: "",
  authorName: "",
  ...p,
});

export const COMMANDS = [
  "ban", "unban", "kick", "timeout", "untimeout", "warn", "warnings", "clear", "lock", "unlock",
  "slowmode", "rank", "top", "avatar", "serverinfo", "userinfo", "say", "embed", "role", "nick",
] as const;

export const LOG_EVENTS = [
  { group: "message", keys: ["messageDelete", "messageEdit", "messageBulkDelete"] },
  { group: "member", keys: ["memberJoin", "memberLeave", "memberNick", "memberRoles", "memberAvatar"] },
  { group: "voice", keys: ["voiceJoin", "voiceLeave", "voiceMove", "voiceMute"] },
  { group: "moderation", keys: ["ban", "unban", "kick", "timeout", "warn"] },
  { group: "server", keys: ["channelCreate", "channelDelete", "channelUpdate", "roleCreate", "roleDelete", "roleUpdate", "serverUpdate", "emojiUpdate", "inviteCreate", "threadCreate"] },
  { group: "bot", keys: ["ticketLogs", "protectionLogs", "applicationLogs"] },
] as const;

export type TicketCategory = { id: string; label: string; emoji: string; description: string; supportRoles: string[]; categoryChannelId: string };
export type AppForm = {
  id: string; name: string; description: string; panelChannelId: string; reviewChannelId: string;
  questions: string[]; acceptRoles: string[]; buttonLabel: string; open: boolean; cooldownHours: number;
};

export function defaultSettings() {
  return {
    general: {
      prefix: "!",
      language: "en" as "en" | "ar",
      nickname: "",
      embedColor: "#22d3ee",
      deleteCommandMessage: false,
      slashCommands: true,
      modRoles: [] as string[],
      commands: Object.fromEntries(COMMANDS.map((c) => [c, { enabled: true, aliases: [] as string[] }])) as Record<string, { enabled: boolean; aliases: string[] }>,
    },
    welcome: {
      enabled: false,
      channelId: "",
      message: "Welcome {user} to **{server}**! You are member #{memberCount}",
      useEmbed: false,
      embed: emptyEmbed({ title: "Welcome!", description: "Hey {user}, enjoy your stay in {server}." }),
      useImage: true,
      image: {
        background: "",
        title: "WELCOME",
        subtitle: "{username}",
        footer: "Member #{memberCount}",
        textColor: "#ffffff",
        accentColor: "#22d3ee",
        overlay: 40,
        avatarShape: "circle" as "circle" | "square",
      },
      dm: { enabled: false, message: "Welcome to {server}, {user}!" },
      autoRoles: [] as string[],
      botRoles: [] as string[],
    },
    leave: { enabled: false, channelId: "", message: "**{username}** left the server. We now have {memberCount} members." },
    tickets: {
      enabled: false,
      panelChannelId: "",
      categoryChannelId: "",
      panelEmbed: emptyEmbed({ title: "Support Tickets", description: "Pick a category below to open a ticket. Our team will help you shortly." }),
      openMessage: "Hello {user}, thanks for reaching out. Support will be with you soon.",
      categories: [
        { id: "support", label: "Technical Support", emoji: "🛠️", description: "", supportRoles: [], categoryChannelId: "" },
        { id: "complaint", label: "Complaints", emoji: "📢", description: "", supportRoles: [], categoryChannelId: "" },
        { id: "question", label: "Questions", emoji: "❓", description: "", supportRoles: [], categoryChannelId: "" },
      ] as TicketCategory[],
      supportRoles: [] as string[],
      transcripts: true,
      transcriptChannelId: "",
      maxOpenPerUser: 1,
      claimEnabled: true,
    },
    protection: {
      antiSpam: { enabled: false, maxMessages: 5, perSeconds: 5, action: "timeout", timeoutMinutes: 10 },
      antiLink: { enabled: false, blockInvites: true, blockAllLinks: false, allowedChannels: [] as string[] },
      antiMassMention: { enabled: false, limit: 5, action: "timeout" },
      antiAlt: { enabled: false, minAgeDays: 7, action: "kick" },
      antiRaid: { enabled: false, joinLimit: 10, perSeconds: 10, action: "lockdown" },
      antiNuke: { enabled: false, channelDeleteLimit: 3, roleDeleteLimit: 3, banLimit: 3, perSeconds: 60, action: "removeRoles" },
      antiBots: { enabled: false },
      antiWebhook: { enabled: false },
      badWords: { enabled: false, words: [] as string[] },
      whitelistRoles: [] as string[],
      whitelistUsers: [] as string[],
    },
    logs: {
      enabled: false,
      defaultChannelId: "",
      channels: {} as Record<string, string>,
      ignoredChannels: [] as string[],
    },
    levels: {
      enabled: false,
      textXpMin: 15,
      textXpMax: 25,
      cooldownSeconds: 60,
      voiceEnabled: true,
      voiceXpPerMinute: 10,
      announce: true,
      levelUpChannelId: "",
      levelUpMessage: "GG {user}, you reached **level {level}**! 🎉",
      rewards: [] as { level: number; roleId: string }[],
      stackRewards: true,
      noXpChannels: [] as string[],
      noXpRoles: [] as string[],
    },
    rules: {
      channelId: "",
      embeds: [emptyEmbed({ title: "📜 Server Rules", description: "1. Be respectful.\n2. No spam or advertising.\n3. Follow Discord's Terms of Service." })],
    },
    autoLine: {
      enabled: false,
      cooldownSeconds: 3,
      lines: [] as { channelId: string; imageUrl: string }[],
    },
    applications: {
      enabled: false,
      forms: [] as AppForm[],
    },
  };
}
export type Settings = ReturnType<typeof defaultSettings>;

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
export function deepMerge<T>(base: T, over: unknown): T {
  if (!isObj(base) || !isObj(over)) return (over === undefined ? base : (over as T));
  const out: Record<string, unknown> = { ...base };
  for (const k of Object.keys(over)) {
    const b = (base as Record<string, unknown>)[k];
    out[k] = isObj(b) && isObj(over[k]) ? deepMerge(b, over[k]) : over[k];
  }
  return out as T;
}

export function fillVars(text: string, v: { user: string; username: string; server: string; memberCount: number | string; level?: number }) {
  return text
    .replaceAll("{user}", v.user)
    .replaceAll("{username}", v.username)
    .replaceAll("{server}", v.server)
    .replaceAll("{memberCount}", String(v.memberCount))
    .replaceAll("{level}", String(v.level ?? 10));
}
