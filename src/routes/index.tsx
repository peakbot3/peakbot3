import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Bot, DoorOpen, FileText, Gauge, Image, ListChecks, ScrollText, Shield, Sparkles, Ticket, Trophy, UserPlus } from "lucide-react";
import mark from "@/assets/peak-mark.png";
import { Button } from "@/components/ui/button";
import { getPublicStats } from "@/lib/api.functions";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "PEAK — The Ultimate Discord Management & Ticket Bot" },
      { name: "description", content: "Add PEAK to Discord: welcome images, tickets, anti-nuke protection, full logs, XP levels, rules embeds and applications." },
      { property: "og:title", content: "PEAK — Discord Management & Ticket Bot" },
      { property: "og:description", content: "Welcome images, tickets, protection, logs, levels and more in one dashboard." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

const FEATURES = [
  { icon: Image, en: ["Welcome Images", "ProBot-style welcome cards with your background, avatar and custom text."], ar: ["صور الترحيب", "بطاقات ترحيب زي ProBot بخلفيتك وصورة العضو ونصك."] },
  { icon: UserPlus, en: ["Auto Roles", "Give roles to new members and bots the moment they join."], ar: ["الرتب التلقائية", "إعطاء رتب للأعضاء والبوتات أول ما يدخلوا."] },
  { icon: Ticket, en: ["Advanced Tickets", "Categories, support roles, claim, and transcripts on close."], ar: ["تذاكر متقدمة", "أقسام، رتب دعم، استلام، وأرشيف المحادثة عند الإغلاق."] },
  { icon: Shield, en: ["Full Protection", "Anti-spam, anti-link, anti-alt, anti-raid and anti-nuke."], ar: ["حماية كاملة", "مانع سبام وروابط وحسابات وهمية وريد وتخريب."] },
  { icon: FileText, en: ["Detailed Logs", "A separate channel for every event: messages, members, voice, moderation."], ar: ["لوقات تفصيلية", "روم لكل حدث: رسائل، أعضاء، صوت، إشراف."] },
  { icon: Trophy, en: ["Levels & XP", "Text and voice XP with automatic level reward roles."], ar: ["المستويات و XP", "نقاط تفاعل كتابي وصوتي مع رتب مكافآت تلقائية."] },
  { icon: ScrollText, en: ["Rules Embeds", "Build beautiful rules embeds like Wicks and post them in one click."], ar: ["قوانين Embed", "صمم قوانين بشكل Embed زي Wicks وانشرها بكبسة."] },
  { icon: ListChecks, en: ["Applications", "Staff applications with questions, review channel and accept roles."], ar: ["التقديمات", "تقديمات بأسئلة وروم مراجعة ورتب قبول."] },
  { icon: Sparkles, en: ["Auto Line", "Automatically send a line GIF after messages in chosen channels."], ar: ["الخط التلقائي", "إرسال صورة خط تلقائي بعد الرسائل برومات محددة."] },
];

function Index() {
  const { t, tr, lang } = useI18n();
  const { data } = useQuery({ queryKey: ["stats"], queryFn: () => getPublicStats(), staleTime: 60_000 });

  return (
    <main>
      <section className="mx-auto flex max-w-5xl flex-col items-center px-4 pb-16 pt-20 text-center">
        <img src={mark} alt="PEAK bot" className="h-40 w-40 animate-float object-contain drop-shadow-[0_0_30px_var(--neon)]" />
        <h1 className="mt-6 font-display text-6xl font-bold tracking-[0.2em] neon-text md:text-8xl">PEAK</h1>
        <p className="mt-4 font-display text-2xl text-gradient md:text-3xl">{t("tagline")}</p>
        <p className="mt-4 max-w-2xl text-muted-foreground">{t("heroSub")}</p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Button size="lg" variant="hero" asChild disabled={!data?.inviteUrl}>
            <a href={data?.inviteUrl ?? "#"} target="_blank" rel="noreferrer"><Bot className="h-5 w-5" /> {t("addToDiscord")}</a>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <Link to="/dashboard"><Gauge className="h-5 w-5" /> {t("dashboard")}</Link>
          </Button>
        </div>
      </section>

      <section className="mx-auto grid max-w-4xl grid-cols-3 gap-4 px-4">
        {[
          [t("servers"), data?.servers],
          [t("users"), data?.users],
          [t("activeTickets"), data?.tickets],
        ].map(([label, n]) => (
          <div key={String(label)} className="glass rounded-2xl p-6 text-center">
            <div className="font-display text-3xl font-bold neon-text md:text-4xl">{(Number(n) || 0).toLocaleString()}</div>
            <div className="mt-1 text-sm text-muted-foreground">{label}</div>
          </div>
        ))}
      </section>

      <section className="mx-auto max-w-7xl px-4 py-20">
        <h2 className="mb-10 text-center text-3xl font-bold">{t("features")}</h2>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => {
            const [title, body] = lang === "ar" ? f.ar : f.en;
            return (
              <div key={f.en[0]} className="glass group rounded-2xl p-6 transition hover:-translate-y-1 hover:shadow-glow">
                <div className="mb-4 inline-flex rounded-xl bg-gradient-primary p-3 text-primary-foreground"><f.icon className="h-6 w-6" /></div>
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{body}</p>
              </div>
            );
          })}
        </div>
      </section>

      <footer className="border-t border-border py-8 text-center text-sm text-muted-foreground">
        <DoorOpen className="mx-auto mb-2 h-4 w-4 opacity-50" />
        © {new Date().getFullYear()} PEAK · {tr("Not affiliated with Discord Inc.", "غير تابع لشركة ديسكورد")}
      </footer>
    </main>
  );
}
