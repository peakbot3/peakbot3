import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useEffect, useState } from "react";
import { Copy, Eye, EyeOff, Loader2, RefreshCw, Save, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sessionQuery } from "@/components/SiteHeader";
import { GuildAvatar } from "./dashboard.index";
import { adminListBotGuilds, getBotCredentials, regenerateSyncKey, saveBotCredentials } from "@/lib/api.functions";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [
      { title: "PEAK Admin" },
      { name: "description", content: "Owner panel for the PEAK bot." },
      { name: "robots", content: "noindex" },
      { property: "og:title", content: "PEAK Admin" },
      { property: "og:description", content: "Owner panel for the PEAK bot." },
    ],
  }),
  component: Admin,
});

function Secret({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [show, setShow] = useState(false);
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" />
        <Button type="button" variant="outline" size="icon" onClick={() => setShow(!show)} aria-label="toggle">
          {show ? <EyeOff /> : <Eye />}
        </Button>
      </div>
    </div>
  );
}

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <Label className="text-muted-foreground">{label}</Label>
      <div className="flex gap-2">
        <Input readOnly value={value} className="font-mono text-xs" />
        <Button variant="outline" size="icon" onClick={() => { navigator.clipboard.writeText(value); toast.success("Copied"); }}><Copy /></Button>
      </div>
    </div>
  );
}

function Admin() {
  const { tr } = useI18n();
  const qc = useQueryClient();
  const session = useQuery(sessionQuery);
  const isAdmin = !!session.data?.admin;
  const creds = useQuery({ queryKey: ["creds"], queryFn: () => getBotCredentials(), enabled: isAdmin });
  const guilds = useQuery({ queryKey: ["bot-guilds"], queryFn: () => adminListBotGuilds(), enabled: isAdmin });
  const save = useServerFn(saveBotCredentials);
  const regen = useServerFn(regenerateSyncKey);
  const [form, setForm] = useState({ clientId: "", clientSecret: "", botToken: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (creds.data) setForm({ clientId: creds.data.clientId, clientSecret: creds.data.clientSecret, botToken: creds.data.botToken });
  }, [creds.data]);

  if (session.isPending && !session.isError) return <Loader2 className="mx-auto mt-24 h-8 w-8 animate-spin text-primary" />;
  if (session.isError)
    return <main className="mx-auto max-w-md p-16 text-center text-destructive">{(session.error as Error).message}</main>;
  if (!isAdmin) return <main className="mx-auto max-w-md p-16 text-center text-muted-foreground">404</main>;
  const setupError = session.data?.setupError;

  const c = creds.data;
  const live = c?.lastPing && Date.now() - new Date(c.lastPing).getTime() < 3 * 60_000;

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-4 py-10">
      <h1 className="text-3xl font-bold">{tr("Admin Panel", "لوحة الأدمن")}</h1>
      {setupError && (
        <p className="glass rounded-2xl p-4 text-sm text-destructive">{setupError}</p>
      )}
      {creds.error && !setupError && (
        <p className="glass rounded-2xl p-4 text-sm text-destructive">{(creds.error as Error).message}</p>
      )}

      <section className="grid gap-6 lg:grid-cols-3">
        <div className="glass space-y-5 rounded-2xl p-6 lg:col-span-2">
          <h2 className="text-xl font-semibold">{tr("Bot credentials", "بيانات البوت")}</h2>
          <div className="space-y-2">
            <Label>Application ID (Client ID)</Label>
            <Input value={form.clientId} onChange={(e) => setForm({ ...form, clientId: e.target.value })} />
          </div>
          <Secret label="Client Secret" value={form.clientSecret} onChange={(v) => setForm({ ...form, clientSecret: v })} />
          <Secret label="Bot Token" value={form.botToken} onChange={(v) => setForm({ ...form, botToken: v })} />
          <Button
            variant="hero"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await save({ data: form });
                toast.success(tr("Saved & synced — the bot picks it up on its next check.", "تم الحفظ — البوت رح يقرأها بالتحديث الجاي."));
                qc.invalidateQueries();
              } catch (e) {
                toast.error((e as Error).message);
              }
              setBusy(false);
            }}
          >
            <Save /> {tr("Save & Sync with Bot", "حفظ ومزامنة مع البوت")}
          </Button>
        </div>

        <div className="glass space-y-4 rounded-2xl p-6">
          <h2 className="text-xl font-semibold">{tr("Status", "الحالة")}</h2>
          <div className="flex items-center gap-3">
            <span className={`h-3 w-3 rounded-full ${live ? "bg-success shadow-glow" : "bg-destructive"}`} />
            <span>{live ? tr("Connected / Live syncing", "متصل / مزامنة مباشرة") : tr("Bot offline (not running)", "البوت مطفي")}</span>
          </div>
          {!live && c && (
            <p className="text-sm text-destructive">{botStatusText(c.botStatus, !!c.lastPing, tr)}</p>
          )}
          {c?.botUser ? (
            <p className="text-sm text-muted-foreground">{tr("Token valid for", "التوكن شغال على")} <b className="text-foreground">{c.botUser.username}</b></p>
          ) : (
            <p className="text-sm text-muted-foreground">{tr("No valid bot token yet.", "ما في توكن صحيح لسا.")}</p>
          )}
          {c?.stats && (
            <p className="text-sm text-muted-foreground">{c.stats.servers} servers · {c.stats.users} users · {c.stats.active_tickets} tickets</p>
          )}
        </div>
      </section>

      {c && (
        <section className="glass space-y-4 rounded-2xl p-6">
          <h2 className="text-xl font-semibold">{tr("Connect the bot", "ربط البوت")}</h2>
          <p className="text-sm text-muted-foreground">
            {tr(
              "Add the Redirect URL in the Discord Developer Portal → OAuth2 → Redirects. Put the Site URL and Sync Key in the bot's .env file.",
              "حط رابط Redirect في Discord Developer Portal ← OAuth2 ← Redirects. وحط رابط الموقع ومفتاح المزامنة بملف .env تبع البوت.",
            )}
          </p>
          <CopyRow label="Redirect URL" value={c.redirectUri} />
          <CopyRow label="SITE_URL" value={c.siteUrl} />
          <div className="flex items-end gap-2">
            <div className="flex-1"><CopyRow label="SYNC_KEY" value={c.syncKey} /></div>
            <Button variant="outline" onClick={async () => { await regen(); qc.invalidateQueries({ queryKey: ["creds"] }); toast.success("New key"); }}>
              <RefreshCw /> {tr("Regenerate", "مفتاح جديد")}
            </Button>
          </div>
        </section>
      )}

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">{tr("Servers the bot is in", "السيرفرات اللي فيها البوت")}</h2>
        {guilds.data?.error && <p className="text-sm text-destructive">{guilds.data.error}</p>}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {guilds.data?.guilds.map((g) => (
            <div key={g.id} className="glass flex items-center gap-4 rounded-2xl p-4">
              <GuildAvatar g={g} size="h-12 w-12" />
              <div className="min-w-0 flex-1 truncate font-semibold">{g.name}</div>
              <Button size="sm" asChild><Link to="/dashboard/$guildId" params={{ guildId: g.id }}><Settings2 /></Link></Button>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function botStatusText(
  st: { code: string; detail: string; at: string } | null,
  pingedBefore: boolean,
  tr: (en: string, ar: string) => string,
) {
  const fresh = st && Date.now() - new Date(st.at).getTime() < 15 * 60_000;
  if (!fresh) {
    return pingedBefore
      ? tr("The bot program stopped. Open it on your host (Render) and check its logs, then restart it.", "برنامج البوت وقف. افتحه على Render وشوف الـ Logs واعمله Restart.")
      : tr(
          "The bot program has not contacted the site yet, so it is not running. Start it on your host (Render → Background Worker, Root Directory: bot) with SITE_URL and SYNC_KEY.",
          "برنامج البوت ما تواصل مع الموقع أبداً، يعني مش شغال. شغّله على Render (Background Worker، والـ Root Directory: bot) وحط SITE_URL و SYNC_KEY.",
        );
  }
  switch (st.code) {
    case "starting":
      return tr("The bot is starting…", "البوت عم يشتغل…");
    case "no_token":
      return tr("The bot is waiting for a Bot Token. Save it above.", "البوت مستني توكن. احفظه فوق.");
    case "bad_token":
      return tr("Discord rejected the Bot Token. Reset it in Developer Portal → Bot and save the new one above.", "ديسكورد رفض التوكن. اعمل Reset Token وحط الجديد فوق.");
    case "intents":
      return tr(
        "Turn on Server Members Intent and Message Content Intent in Developer Portal → Bot → Privileged Gateway Intents. The bot tries again in 10 minutes.",
        "فعّل Server Members Intent و Message Content Intent من Developer Portal ← Bot ← Privileged Gateway Intents. البوت بيرجع يجرب بعد 10 دقايق.",
      );
    case "rate_limited":
      return tr("Discord asked the bot to slow down (429). It waits 30 minutes before trying again — do nothing.", "ديسكورد طلب من البوت يخفف (429). البوت بيستنى نص ساعة لحاله، لا تعمل إشي.");
    case "network":
      return tr("The bot cannot reach Discord right now. It retries in 2 minutes.", "البوت مش قادر يوصل لديسكورد هلأ. بيرجع يجرب بعد دقيقتين.");
    default:
      return `${tr("Bot error", "خطأ بالبوت")}: ${st.detail || st.code}`;
  }
}
