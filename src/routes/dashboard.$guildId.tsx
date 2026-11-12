import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useEffect, useMemo, useState } from "react";
import { z } from "zod";
import {
  ArrowLeft, Bot, FileText, Gamepad2, Landmark, Hand, ListChecks, Loader2, MailWarning, MessageSquareReply, Mic, Minus, ScrollText, Settings, Shield, Smile, SmilePlus, Terminal, Ticket, Trophy, UserCog, UserPlus,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DashCtx, setPath } from "@/components/dash/fields";
import {
  ApplicationsModule, AutoLineModule, AutoRolesModule, BankModule, CommandsModule, GamesModule, GeneralModule, LevelsModule, LogsModule, ProtectionModule, RulesModule, TicketsModule, WelcomeModule,
} from "@/components/dash/modules";
import { AutoReactModule, AutoReplyModule, BotProfileModule, ModDmModule, ReactionRolesModule, TempVoiceModule } from "@/components/dash/extra-modules";
import { GuildAvatar } from "./dashboard.index";
import { getGuildData, saveGuildSettings } from "@/lib/api.functions";
import { useI18n, type TKey } from "@/lib/i18n";
import type { Settings as S } from "@/lib/settings";

const TABS: { key: string; t: TKey; icon: typeof Settings; C: () => React.JSX.Element }[] = [
  { key: "general", t: "general", icon: Settings, C: GeneralModule },
  { key: "botprofile", t: "botProfile", icon: UserCog, C: BotProfileModule },
  { key: "commands", t: "commands", icon: Terminal, C: CommandsModule },
  { key: "welcome", t: "welcome", icon: Hand, C: WelcomeModule },
  { key: "autoroles", t: "autoRoles", icon: UserPlus, C: AutoRolesModule },
  { key: "reactionroles", t: "reactionRoles", icon: SmilePlus, C: ReactionRolesModule },
  { key: "tickets", t: "tickets", icon: Ticket, C: TicketsModule },
  { key: "protection", t: "protection", icon: Shield, C: ProtectionModule },
  { key: "moddm", t: "modDm", icon: MailWarning, C: ModDmModule },
  { key: "logs", t: "logs", icon: FileText, C: LogsModule },
  { key: "levels", t: "levels", icon: Trophy, C: LevelsModule },
  { key: "rules", t: "rules", icon: ScrollText, C: RulesModule },
  { key: "autoline", t: "autoLine", icon: Minus, C: AutoLineModule },
  { key: "autoreact", t: "autoReact", icon: Smile, C: AutoReactModule },
  { key: "autoreply", t: "autoReply", icon: MessageSquareReply, C: AutoReplyModule },
  { key: "tempvoice", t: "tempVoice", icon: Mic, C: TempVoiceModule },
  { key: "applications", t: "applications", icon: ListChecks, C: ApplicationsModule },
  { key: "games", t: "games", icon: Gamepad2, C: GamesModule },
  { key: "bank", t: "bank", icon: Landmark, C: BankModule },
];

export const Route = createFileRoute("/dashboard/$guildId")({
  validateSearch: z.object({ tab: z.string().optional() }),
  head: () => ({
    meta: [
      { title: "Server Settings — PEAK Dashboard" },
      { name: "description", content: "Configure PEAK for your Discord server." },
      { property: "og:title", content: "Server Settings — PEAK Dashboard" },
      { property: "og:description", content: "Configure PEAK for your Discord server." },
    ],
  }),
  component: GuildPage,
});

function GuildPage() {
  const { guildId } = Route.useParams();
  const { tab = "general" } = Route.useSearch();
  const { t } = useI18n();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["guild", guildId], queryFn: () => getGuildData({ data: { guildId } }), retry: false, staleTime: 5 * 60_000, refetchOnWindowFocus: false });
  const save = useServerFn(saveGuildSettings);
  const [draft, setDraft] = useState<S | null>(null);
  const [busy, setBusy] = useState(false);

  const server = q.data && !q.data.botMissing ? q.data : null;
  useEffect(() => {
    if (server) setDraft(server.settings as S);
  }, [server]);
  const dirty = useMemo(() => !!server && !!draft && JSON.stringify(draft) !== JSON.stringify(server.settings), [draft, server]);

  if (q.isLoading) return <Loader2 className="mx-auto mt-24 h-8 w-8 animate-spin text-primary" />;
  if (q.error) return <Centered>{(q.error as Error).message}<Back /></Centered>;
  if (q.data?.botMissing) return <Centered>PEAK is not in this server yet.<Back /></Centered>;
  if (!server || !draft) return null;

  const Active = (TABS.find((x) => x.key === tab) ?? TABS[0]!).C;

  const onSave = async () => {
    setBusy(true);
    try {
      await save({ data: { guildId, settings: draft as unknown as Record<string, unknown> } });
      await qc.invalidateQueries({ queryKey: ["guild", guildId] });
      toast.success(t("saved"));
    } catch (e) {
      toast.error((e as Error).message);
    }
    setBusy(false);
  };

  return (
    <DashCtx.Provider value={{ s: draft, set: (p, v) => setDraft((d) => setPath(d!, p, v)), channels: server.channels, roles: server.roles, emojis: server.emojis ?? [], guild: server.guild, dirty }}>
      <div className="mx-auto flex max-w-7xl gap-6 px-4 py-6">
        <aside className="sticky top-20 hidden h-[calc(100vh-6rem)] w-60 shrink-0 overflow-y-auto md:block">
          <div className="glass mb-4 flex items-center gap-3 rounded-2xl p-3">
            <GuildAvatar g={server.guild} size="h-10 w-10" />
            <div className="min-w-0">
              <div className="truncate font-semibold">{server.guild.name}</div>
              <div className="text-xs text-muted-foreground">{server.guild.memberCount} members</div>
            </div>
          </div>
          <nav className="space-y-1">
            {TABS.map((x) => (
              <Link
                key={x.key}
                to="/dashboard/$guildId"
                params={{ guildId }}
                search={{ tab: x.key }}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${tab === x.key ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-secondary hover:text-foreground"}`}
              >
                <x.icon className="h-4 w-4" /> {t(x.t)}
              </Link>
            ))}
          </nav>
          <Link to="/dashboard" className="mt-6 flex items-center gap-2 px-3 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3 w-3" /> {t("back")}</Link>
        </aside>

        <main className="min-w-0 flex-1 pb-28">
          <div className="mb-4 flex gap-2 overflow-x-auto md:hidden">
            {TABS.map((x) => (
              <Link key={x.key} to="/dashboard/$guildId" params={{ guildId }} search={{ tab: x.key }} className={`shrink-0 rounded-full px-3 py-1.5 text-xs ${tab === x.key ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>
                {t(x.t)}
              </Link>
            ))}
          </div>
          <h1 className="mb-6 flex items-center gap-2 text-2xl font-bold"><Bot className="h-6 w-6 text-primary" /> {t((TABS.find((x) => x.key === tab) ?? TABS[0]!).t)}</h1>
          <Active />
        </main>
      </div>

      {dirty && (
        <div className="fixed inset-x-0 bottom-4 z-50 mx-auto flex w-[min(95%,640px)] items-center justify-between gap-3 rounded-2xl glass p-3 shadow-glow">
          <span className="text-sm">{t("unsaved")}</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setDraft(server.settings as S)}>{t("reset")}</Button>
            <Button variant="hero" onClick={onSave} disabled={busy}>{busy && <Loader2 className="animate-spin" />} {t("save")}</Button>
          </div>
        </div>
      )}
    </DashCtx.Provider>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto flex max-w-md flex-col items-center gap-4 p-16 text-center text-muted-foreground">{children}</main>;
}
function Back() {
  const { t } = useI18n();
  return <Button asChild variant="outline"><Link to="/dashboard">{t("back")}</Link></Button>;
}
