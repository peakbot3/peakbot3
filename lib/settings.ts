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

// Games the PEAK games system can run (ids are shared with the Python bot).
export const GAMES = [
  { id: "roulette", kind: "server", emoji: "🎡", en: "Roulette", ar: "روليت" },
  { id: "mafia", kind: "server", emoji: "🕵️", en: "Mafia", ar: "مافيا" },
  { id: "chairs", kind: "server", emoji: "🪑", en: "Chairs", ar: "كراسي" },
  { id: "rps", kind: "server", emoji: "✂️", en: "Rock Paper Scissors", ar: "حجرة ورقة مقص" },
  { id: "dice", kind: "server", emoji: "🎲", en: "Dice", ar: "نرد" },
  { id: "deathwheel", kind: "server", emoji: "☠️", en: "Death Wheel", ar: "عجلة الموت" },
  { id: "bomb", kind: "server", emoji: "💣", en: "Bomb", ar: "قنبلة" },
  { id: "xo", kind: "duel", emoji: "❌", en: "XO", ar: "اكس او" },
  { id: "hotxo", kind: "duel", emoji: "🔥", en: "Hot XO", ar: "اكس او نار" },
  { id: "fast", kind: "mini", emoji: "⚡", en: "Fast Type", ar: "اسرع" },
  { id: "reverse", kind: "mini", emoji: "🔁", en: "Text Reverse", ar: "اعكس" },
  { id: "split", kind: "mini", emoji: "✂️", en: "Text Split", ar: "فكك" },
  { id: "merge", kind: "mini", emoji: "🔗", en: "Merge Text", ar: "ركب" },
  { id: "flag", kind: "mini", emoji: "🚩", en: "Guess the Flag", ar: "اعلام" },
  { id: "capital", kind: "mini", emoji: "🏛️", en: "Capitals", ar: "عواصم" },
  { id: "math", kind: "mini", emoji: "➗", en: "Math", ar: "حساب" },
  { id: "sort", kind: "mini", emoji: "🔢", en: "Sort Numbers", ar: "رتب" },
  { id: "emoji", kind: "mini", emoji: "😀", en: "Find the Emoji", ar: "ايموجي" },
] as const;

export type TicketCategory = { id: string; label: string; emoji: string; description: string; supportRoles: string[]; categoryChannelId: string };
export type ReactionRoleItem = { emoji: string; roleId: string; label: string };
export type ReactionRolePanel = {
  id: string; channelId: string; messageId: string; mode: "reactions" | "buttons"; unique: boolean;
  embed: Embed; items: ReactionRoleItem[];
};
export type AutoReactRule = { id: string; channels: string[]; emojis: string[]; onlyImages: boolean };
export type AutoReplyItem = {
  id: string; triggers: string[]; match: "exact" | "contains" | "startsWith"; response: string;
  asReply: boolean; asEmbed: boolean; channels: string[]; enabled: boolean;
};

// Temp voice control panel buttons (ids are shared with the Python bot). 3 rows of 5, like the panel image.
export const TEMP_VOICE_BUTTONS = [
  { id: "name", emoji: "✏️", en: "Name", ar: "الاسم" },
  { id: "limit", emoji: "👥", en: "Limit", ar: "العدد" },
  { id: "privacy", emoji: "🔒", en: "Privacy", ar: "الخصوصية" },
  { id: "waiting", emoji: "⏳", en: "Waiting room", ar: "غرفة الانتظار" },
  { id: "chat", emoji: "💬", en: "Chat", ar: "الشات" },
  { id: "trust", emoji: "✅", en: "Trust", ar: "توثيق" },
  { id: "untrust", emoji: "❎", en: "Untrust", ar: "إلغاء التوثيق" },
  { id: "invite", emoji: "📞", en: "Invite", ar: "دعوة" },
  { id: "kick", emoji: "👢", en: "Kick", ar: "طرد" },
  { id: "region", emoji: "🌍", en: "Region", ar: "المنطقة" },
  { id: "block", emoji: "🚫", en: "Block", ar: "حظر" },
  { id: "unblock", emoji: "🔓", en: "Unblock", ar: "فك الحظر" },
  { id: "delete", emoji: "🗑️", en: "Delete", ar: "حذف" },
  { id: "claim", emoji: "👑", en: "Claim", ar: "استلام" },
  { id: "transfer", emoji: "🔁", en: "Transfer", ar: "نقل الملكية" },
] as const;

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
      // Bot picture in this server only (Discord CDN link, set from the Bot profile tab). Empty = normal picture.
      botAvatar: "",
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
      // DM the ticket owner a summary card (+ transcript file) when the ticket closes. Off by default.
      dmOnClose: {
        enabled: false,
        sendTranscript: true,
        message: "We hope you have a great day!",
      },
      // "Add member" / "Remove member" buttons inside tickets (pick people from a list). Off by default.
      addMember: {
        enabled: false,
        who: "support" as "support" | "owner",
      },
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
    games: {
      enabled: false,
      prefix: "-",
      channels: [] as string[],
      managerRoles: [] as string[],
      lobbySeconds: 30,
      maxPlayers: 20,
      winnerCoins: 100,
      miniCoins: 20,
      list: Object.fromEntries(GAMES.map((x) => [x.id, true])) as Record<string, boolean>,
      // -games / -العاب sends the games list (optional picture); -اوامر sends the bank commands.
      listImage: "",
    },
    bank: {
      enabled: false,
      currencyName: "Coins",
      currencyEmoji: "🪙",
      startBalance: 0,
      channels: [] as string[],
      adminRoles: [] as string[],
      dailyAmount: 500,
      workMin: 50,
      workMax: 250,
      workCooldownMinutes: 60,
      transferTax: 5,
      rob: { enabled: true, chance: 40, maxPercent: 20, cooldownMinutes: 120, fine: 10 },
      gamble: { enabled: true, maxBet: 10000 },
      interest: { enabled: false, percent: 1 },
    },
    // Pick a role by clicking an emoji (or a button) under a message the bot posts.
    reactionRoles: {
      enabled: false,
      panels: [] as ReactionRolePanel[],
    },
    // Every new message in these channels gets these emoji reactions.
    autoReact: {
      enabled: false,
      rules: [] as AutoReactRule[],
    },
    // Join-to-create voice rooms with a control panel.
    tempVoice: {
      enabled: false,
      joinChannelId: "",
      categoryId: "",
      nameTemplate: "{username}'s room",
      defaultLimit: 0,
      panelInVoiceChat: true,
      panelChannelId: "",
      panelImage: "",
      buttonEmojis: Object.fromEntries(TEMP_VOICE_BUTTONS.map((b) => [b.id, b.emoji])) as Record<string, string>,
    },
    autoReply: {
      enabled: false,
      cooldownSeconds: 3,
      replies: [] as AutoReplyItem[],
    },
    // Private message to the member when staff punish them with a PEAK command.
    modDm: {
      enabled: false,
      showModerator: false,
      warn: { enabled: true, message: "⚠️ You got warned in **{server}**." },
      timeout: { enabled: true, message: "🔇 You got timed out in **{server}** for {duration}." },
      kick: { enabled: true, message: "👢 You got kicked from **{server}**." },
      ban: { enabled: true, message: "🔨 You got banned from **{server}**." },
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
