import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Lang = "en" | "ar";
const dict = {
  en: {
    tagline: "The Ultimate Discord Management & Ticket Bot",
    heroSub: "Welcome images, tickets, full protection, logs, levels, rules, applications, games, a bank and more — all controlled from one dashboard.",
    addToDiscord: "Add to Discord", dashboard: "Dashboard", login: "Login with Discord", logout: "Log out",
    servers: "Servers", users: "Users", activeTickets: "Active Tickets", features: "Everything your server needs",
    adminPanel: "Admin Panel", yourServers: "Your servers", pickServer: "Pick a server you manage. Servers without PEAK need the bot added first.",
    manage: "Manage", invite: "Add bot", signInFirst: "Sign in with Discord to see your servers.",
    save: "Save changes", saved: "Changes saved — the bot will sync automatically.", unsaved: "You have unsaved changes", reset: "Reset",
    adminLogin: "Admin sign in", discordId: "Discord ID", password: "Password", signIn: "Sign in", wrong: "Wrong ID or password",
    send: "Send to channel", sent: "Message sent", none: "None", select: "Select…", enabled: "Enabled",
    general: "General", welcome: "Welcome & Leave", autoRoles: "Auto Roles", tickets: "Tickets", protection: "Protection",
    logs: "Logs", levels: "Levels & XP", rules: "Rules", autoLine: "Auto Line", applications: "Applications", commands: "Commands", games: "Games", bank: "Bank",
    reactionRoles: "Emoji Roles", autoReact: "Auto Emoji", tempVoice: "Temp Voice", autoReply: "Auto Reply", modDm: "Punishment DMs", botProfile: "Bot Profile",
    back: "Back to servers",
  },
  ar: {
    tagline: "البوت الأقوى لإدارة سيرفرات ديسكورد والتذاكر",
    heroSub: "صور ترحيب، تذاكر، حماية كاملة، لوقات، مستويات، قوانين، تقديمات، ألعاب، بنك والمزيد — كلها من لوحة وحدة.",
    addToDiscord: "أضف البوت لديسكورد", dashboard: "لوحة التحكم", login: "تسجيل الدخول بديسكورد", logout: "تسجيل الخروج",
    servers: "السيرفرات", users: "المستخدمين", activeTickets: "التذاكر المفتوحة", features: "كل اللي يحتاجه سيرفرك",
    adminPanel: "لوحة الأدمن", yourServers: "سيرفراتك", pickServer: "اختار سيرفر أنت أدمن فيه. السيرفرات اللي ما فيها PEAK لازم تضيف البوت أول.",
    manage: "تحكم", invite: "أضف البوت", signInFirst: "سجّل دخول بديسكورد عشان تشوف سيرفراتك.",
    save: "حفظ التغييرات", saved: "تم الحفظ — البوت رح يتحدث تلقائياً.", unsaved: "عندك تغييرات ما انحفظت", reset: "تراجع",
    adminLogin: "دخول الأدمن", discordId: "ايدي ديسكورد", password: "كلمة السر", signIn: "دخول", wrong: "الايدي أو كلمة السر غلط",
    send: "إرسال للروم", sent: "تم الإرسال", none: "بدون", select: "اختار…", enabled: "مفعّل",
    general: "الإعدادات العامة", welcome: "الترحيب والمغادرة", autoRoles: "الرتب التلقائية", tickets: "التذاكر", protection: "الحماية",
    logs: "اللوقات", levels: "المستويات و XP", rules: "القوانين", autoLine: "الخط التلقائي", applications: "التقديمات", commands: "الأوامر", games: "الألعاب", bank: "البنك",
    reactionRoles: "رتب بالإيموجي", autoReact: "الإيموجي التلقائي", tempVoice: "الرومات المؤقتة", autoReply: "الرد التلقائي", modDm: "رسائل العقوبات", botProfile: "إعدادات البوت",
    back: "رجوع للسيرفرات",
  },
} as const;
export type TKey = keyof typeof dict.en;

const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: (k: TKey) => string; tr: (en: string, ar: string) => string }>({
  lang: "en",
  setLang: () => {},
  t: (k) => dict.en[k],
  tr: (en) => en,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  useEffect(() => {
    const saved = localStorage.getItem("peak-lang");
    if (saved === "ar" || saved === "en") setLangState(saved);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);
  const setLang = (l: Lang) => {
    localStorage.setItem("peak-lang", l);
    setLangState(l);
  };
  return (
    <Ctx.Provider value={{ lang, setLang, t: (k) => dict[lang][k], tr: (en, ar) => (lang === "ar" ? ar : en) }}>
      {children}
    </Ctx.Provider>
  );
}
export const useI18n = () => useContext(Ctx);
