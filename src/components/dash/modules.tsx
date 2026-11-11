import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { Plus, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { sendToChannel } from "@/lib/api.functions";
import { useI18n } from "@/lib/i18n";
import { COMMANDS, GAMES, LOG_EVENTS, emptyEmbed, fillVars, type AppForm, type TicketCategory } from "@/lib/settings";
import { DiscordMessage, EmbedEditor, toDiscordEmbed } from "./embed";
import {
  Card, ChannelMulti, ChannelSelect, EnableSwitch, Field, NumberInput, RoleSelect, SelectInput, TextArea, TextInput, ToggleRow, VarHint, useDash,
} from "./fields";

const uid = () => Math.random().toString(36).slice(2, 10);
const inputCls = "h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm";

function useSend() {
  const { guild } = useDash();
  const { t } = useI18n();
  const send = useServerFn(sendToChannel);
  const [busy, setBusy] = useState(false);
  return {
    busy,
    go: async (channelId: string, payload: { content?: string; embeds?: object[]; components?: object[] }) => {
      if (!channelId) { toast.error("Pick a channel first"); return; }
      setBusy(true);
      try {
        await send({ data: { guildId: guild.id, channelId, ...payload } as never });
        toast.success(t("sent"));
      } catch (e) {
        toast.error((e as Error).message);
      }
      setBusy(false);
    },
  };
}

// ---------------- General ----------------
export function GeneralModule() {
  const { tr } = useI18n();
  return (
    <div className="space-y-6">
      <Card title={tr("Bot settings", "إعدادات البوت")}>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={tr("Command prefix", "بادئة الأوامر")} hint={tr("Example: ! or -", "مثال: ! أو -")}><TextInput path="general.prefix" maxLength={5} /></Field>
          <Field label={tr("Bot language", "لغة البوت")}>
            <SelectInput path="general.language" options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} />
          </Field>
          <Field label={tr("Bot nickname in this server", "اسم البوت بالسيرفر")}><TextInput path="general.nickname" maxLength={32} placeholder="PEAK" /></Field>
          <Field label={tr("Embed color", "لون الـ Embed")}><ColorInput path="general.embedColor" /></Field>
        </div>
        <ToggleRow path="general.slashCommands" label={tr("Slash commands", "أوامر السلاش")} desc={tr("Enable /commands alongside the prefix.", "تفعيل أوامر / مع البادئة.")} />
        <ToggleRow path="general.deleteCommandMessage" label={tr("Delete command message", "حذف رسالة الأمر")} desc={tr("Remove the user's command after it runs.", "حذف رسالة الأمر بعد تنفيذه.")} />
        <Field label={tr("Moderator roles", "رتب المشرفين")} hint={tr("Can use moderation commands without Discord permissions.", "يقدروا يستخدموا أوامر الإشراف.")}>
          <RoleSelect path="general.modRoles" />
        </Field>
      </Card>
    </div>
  );
}

function ColorInput({ path }: { path: string }) {
  const { s, set } = useDash();
  const v = path.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)?.[k], s) as string;
  return <input type="color" value={v} onChange={(e) => set(path, e.target.value)} className="h-9 w-20 rounded-md border border-input bg-transparent" />;
}

// ---------------- Commands ----------------
export function CommandsModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  return (
    <Card title={tr("Commands", "الأوامر")} desc={tr(`Prefix: ${s.general.prefix} — turn commands on/off and add aliases (comma separated).`, `البادئة: ${s.general.prefix} — شغّل/أطفي الأوامر وضيف اختصارات (افصل بفاصلة).`)}>
      <div className="grid gap-3 md:grid-cols-2">
        {COMMANDS.map((c) => {
          const cmd = s.general.commands[c] ?? { enabled: true, aliases: [] };
          return (
            <div key={c} className="flex items-center gap-3 rounded-xl bg-secondary/40 p-3">
              <code className="w-28 shrink-0 text-primary">{s.general.prefix}{c}</code>
              <input
                className={inputCls}
                placeholder={tr("aliases", "اختصارات")}
                value={cmd.aliases.join(", ")}
                onChange={(e) => set(`general.commands.${c}.aliases`, e.target.value.split(",").map((a) => a.trim()).filter(Boolean).slice(0, 5))}
              />
              <Switch checked={cmd.enabled} onCheckedChange={(v) => set(`general.commands.${c}.enabled`, v)} />
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ---------------- Welcome ----------------
export function WelcomeImagePreview() {
  const { s, guild } = useDash();
  const im = s.welcome.image;
  const vars = { user: "@NewMember", username: "NewMember", server: guild.name, memberCount: guild.memberCount + 1 };
  return (
    <div
      className="relative flex aspect-[1024/450] w-full flex-col items-center justify-center overflow-hidden rounded-xl bg-gradient-primary text-center"
      style={im.background ? { backgroundImage: `url(${im.background})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}
    >
      <div className="absolute inset-0 bg-background" style={{ opacity: im.overlay / 100 }} />
      <div className="relative flex flex-col items-center gap-2" style={{ color: im.textColor }}>
        <img
          src="https://cdn.discordapp.com/embed/avatars/1.png"
          alt=""
          className={`h-20 w-20 border-4 md:h-28 md:w-28 ${im.avatarShape === "circle" ? "rounded-full" : "rounded-xl"}`}
          style={{ borderColor: im.accentColor }}
        />
        <div className="font-display text-2xl font-bold tracking-widest md:text-4xl">{fillVars(im.title, vars)}</div>
        <div className="text-lg md:text-xl" style={{ color: im.accentColor }}>{fillVars(im.subtitle, vars)}</div>
        <div className="text-xs opacity-80 md:text-sm">{fillVars(im.footer, vars)}</div>
      </div>
    </div>
  );
}

export function WelcomeModule() {
  const { s, guild } = useDash();
  const { tr } = useI18n();
  const vars = { user: "@NewMember", username: "NewMember", server: guild.name, memberCount: guild.memberCount + 1 };
  return (
    <div className="space-y-6">
      <Card title={tr("Welcome messages", "رسائل الترحيب")} action={<EnableSwitch path="welcome.enabled" />}>
        <Field label={tr("Welcome channel", "روم الترحيب")}><ChannelSelect path="welcome.channelId" /></Field>
        <Field label={tr("Message", "الرسالة")}>
          <TextArea path="welcome.message" rows={3} />
          <VarHint />
        </Field>
        <ToggleRow path="welcome.useImage" label={tr("Welcome image card", "صورة ترحيب")} desc={tr("Generate a ProBot-style image with the member's avatar.", "توليد صورة زي ProBot فيها صورة العضو.")} />
        {s.welcome.useImage && (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              <Field label={tr("Background image URL", "رابط صورة الخلفية")} hint="1024×450 recommended"><TextInput path="welcome.image.background" placeholder="https://…" /></Field>
              <Field label={tr("Title", "العنوان")}><TextInput path="welcome.image.title" maxLength={40} /></Field>
              <Field label={tr("Subtitle", "النص الثاني")}><TextInput path="welcome.image.subtitle" maxLength={60} /></Field>
              <Field label={tr("Footer text", "النص السفلي")}><TextInput path="welcome.image.footer" maxLength={60} /></Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label={tr("Text", "النص")}><ColorInput path="welcome.image.textColor" /></Field>
                <Field label={tr("Accent", "اللون")}><ColorInput path="welcome.image.accentColor" /></Field>
                <Field label={tr("Darken %", "تعتيم %")}><NumberInput path="welcome.image.overlay" max={90} /></Field>
              </div>
              <Field label={tr("Avatar shape", "شكل الصورة")}>
                <SelectInput path="welcome.image.avatarShape" options={[{ value: "circle", label: "Circle" }, { value: "square", label: "Square" }]} />
              </Field>
            </div>
            <WelcomeImagePreview />
          </div>
        )}
        <ToggleRow path="welcome.useEmbed" label={tr("Send as embed", "إرسال كـ Embed")} />
        {s.welcome.useEmbed && <EmbedEditor path="welcome.embed" />}
        <div>
          <div className="mb-2 text-sm text-muted-foreground">{tr("Preview", "معاينة")}</div>
          <DiscordMessage content={fillVars(s.welcome.message, vars)} embed={s.welcome.useEmbed ? { ...s.welcome.embed, title: fillVars(s.welcome.embed.title, vars), description: fillVars(s.welcome.embed.description, vars) } : null}>
            {s.welcome.useImage && <div className="mt-2 max-w-md"><WelcomeImagePreview /></div>}
          </DiscordMessage>
        </div>
      </Card>
      <Card title={tr("Direct message on join", "رسالة خاصة عند الدخول")} action={<EnableSwitch path="welcome.dm.enabled" />}>
        <TextArea path="welcome.dm.message" rows={2} />
      </Card>
      <Card title={tr("Leave messages", "رسائل المغادرة")} action={<EnableSwitch path="leave.enabled" />}>
        <Field label={tr("Leave channel", "روم المغادرة")}><ChannelSelect path="leave.channelId" /></Field>
        <Field label={tr("Message", "الرسالة")}><TextArea path="leave.message" rows={2} /><VarHint /></Field>
      </Card>
    </div>
  );
}

export function AutoRolesModule() {
  const { tr } = useI18n();
  return (
    <Card title={tr("Auto roles", "الرتب التلقائية")} desc={tr("Roles are added one at a time with a short delay to respect Discord rate limits. PEAK's role must be above these roles.", "الرتب تنعطى وحدة وحدة مع تأخير بسيط عشان قوانين ديسكورد. لازم رتبة البوت تكون أعلى منها.")}>
      <Field label={tr("Roles for new members", "رتب الأعضاء الجدد")}><RoleSelect path="welcome.autoRoles" /></Field>
      <Field label={tr("Roles for new bots", "رتب البوتات الجديدة")}><RoleSelect path="welcome.botRoles" /></Field>
    </Card>
  );
}

// ---------------- Tickets ----------------
export function TicketsModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const { go, busy } = useSend();
  const cats = s.tickets.categories;
  const upCat = (i: number, patch: Partial<TicketCategory>) => set("tickets.categories", cats.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const panel = () =>
    go(s.tickets.panelChannelId, {
      embeds: [toDiscordEmbed(s.tickets.panelEmbed)],
      components: [
        {
          type: 1,
          components: [
            {
              type: 3,
              custom_id: "peak:ticket:open",
              placeholder: tr("Choose a ticket category", "اختار قسم التذكرة"),
              options: cats.slice(0, 25).map((c) => ({ label: c.label.slice(0, 100), value: c.id, description: c.description?.slice(0, 100) || undefined, emoji: c.emoji ? { name: c.emoji } : undefined })),
            },
          ],
        },
      ],
    });
  return (
    <div className="space-y-6">
      <Card title={tr("Ticket system", "نظام التذاكر")} action={<EnableSwitch path="tickets.enabled" />}>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={tr("Panel channel", "روم إنشاء التذاكر")}><ChannelSelect path="tickets.panelChannelId" /></Field>
          <Field label={tr("Default ticket category", "الكاتيجوري الافتراضي")}><ChannelSelect path="tickets.categoryChannelId" kind="category" /></Field>
          <Field label={tr("Support roles", "رتب الدعم الفني")}><RoleSelect path="tickets.supportRoles" /></Field>
          <Field label={tr("Max open tickets per user", "أقصى عدد تذاكر للعضو")}><NumberInput path="tickets.maxOpenPerUser" min={1} max={10} /></Field>
        </div>
        <Field label={tr("Message inside new tickets", "الرسالة داخل التذكرة")}><TextArea path="tickets.openMessage" rows={2} /></Field>
        <ToggleRow path="tickets.claimEnabled" label={tr("Claim button", "زر الاستلام")} />
        <ToggleRow path="tickets.transcripts" label={tr("Save transcripts", "حفظ سجل التذكرة")} desc={tr("Send a transcript file to the archive channel on close.", "إرسال ملف المحادثة لروم الأرشيف عند الإغلاق.")} />
        {s.tickets.transcripts && <Field label={tr("Transcript channel", "روم الأرشيف")}><ChannelSelect path="tickets.transcriptChannelId" /></Field>}
      </Card>

      <Card
        title={tr("Message to the member when a ticket closes", "رسالة خاصة للعضو لما تتسكر التذكرة")}
        desc={tr("PEAK DMs the ticket owner a summary card: ticket number, staff, who claimed it, open time and the transcript file.", "البوت يبعت لصاحب التذكرة عالخاص: رقم التذكرة، المشرفين، مين استلمها، وقت فتحها، وملف التذكرة.")}
        action={<EnableSwitch path="tickets.dmOnClose.enabled" />}
      >
        {s.tickets.dmOnClose.enabled && (
          <>
            <ToggleRow path="tickets.dmOnClose.sendTranscript" label={tr("Attach the transcript file", "إرفاق ملف التذكرة")} />
            <Field label={tr("Closing line", "جملة الختام")}><TextInput path="tickets.dmOnClose.message" maxLength={200} /></Field>
            <TicketDmPreview />
          </>
        )}
      </Card>

      <Card
        title={tr("Add people to a ticket", "إضافة أشخاص للتذكرة")}
        desc={tr("Shows Add member / Remove member buttons inside tickets. Pick people from a list.", "يظهر زر إضافة عضو وإزالة عضو داخل التذكرة، وتختار الأشخاص من قائمة.")}
        action={<EnableSwitch path="tickets.addMember.enabled" />}
      >
        {s.tickets.addMember.enabled && (
          <Field label={tr("Who can add people", "مين يقدر يضيف")}>
            <SelectInput
              path="tickets.addMember.who"
              options={[
                { value: "support", label: tr("Support team only", "فريق الدعم بس") },
                { value: "owner", label: tr("Support team and the ticket owner", "فريق الدعم وصاحب التذكرة") },
              ]}
            />
          </Field>
        )}
      </Card>

      <Card
        title={tr("Ticket categories", "أقسام التذاكر")}
        action={
          <Button size="sm" variant="outline" disabled={cats.length >= 25} onClick={() => set("tickets.categories", [...cats, { id: uid(), label: "New", emoji: "🎫", description: "", supportRoles: [], categoryChannelId: "" }])}>
            <Plus /> {tr("Add", "إضافة")}
          </Button>
        }
      >
        {cats.map((c, i) => (
          <div key={c.id} className="grid gap-3 rounded-xl bg-secondary/40 p-4 md:grid-cols-[80px_1fr_1fr_auto]">
            <input className={inputCls} value={c.emoji} onChange={(e) => upCat(i, { emoji: e.target.value })} maxLength={8} />
            <input className={inputCls} value={c.label} onChange={(e) => upCat(i, { label: e.target.value })} maxLength={80} placeholder="Label" />
            <input className={inputCls} value={c.description} onChange={(e) => upCat(i, { description: e.target.value })} maxLength={100} placeholder="Description" />
            <Button variant="ghost" size="icon" onClick={() => set("tickets.categories", cats.filter((_, j) => j !== i))}><Trash2 /></Button>
            <div className="md:col-span-2"><RoleSelect value={c.supportRoles} onChange={(v) => upCat(i, { supportRoles: v })} /></div>
            <div className="md:col-span-2"><ChannelSelect kind="category" value={c.categoryChannelId} onChange={(v) => upCat(i, { categoryChannelId: v })} /></div>
          </div>
        ))}
      </Card>

      <Card title={tr("Panel embed", "شكل لوحة التذاكر")} action={<Button size="sm" variant="hero" disabled={busy} onClick={panel}><Send /> {tr("Send panel", "إرسال اللوحة")}</Button>}>
        <EmbedEditor path="tickets.panelEmbed" />
        <DiscordMessage embed={s.tickets.panelEmbed}>
          <div className="mt-2 max-w-md rounded-md border border-border bg-background/60 px-3 py-2 text-muted-foreground">{tr("Choose a ticket category", "اختار قسم التذكرة")} ▾</div>
        </DiscordMessage>
      </Card>
    </div>
  );
}

// ---------------- Protection ----------------
const actions = (tr: (a: string, b: string) => string) => [
  { value: "timeout", label: tr("Timeout", "كتم") },
  { value: "kick", label: tr("Kick", "طرد") },
  { value: "ban", label: tr("Ban", "باند") },
  { value: "delete", label: tr("Delete only", "حذف فقط") },
];
export function ProtectionModule() {
  const { tr } = useI18n();
  const { s, set } = useDash();
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Anti-Spam" desc={tr("Stops message flooding.", "يمنع التكرار المزعج.")} action={<EnableSwitch path="protection.antiSpam.enabled" />}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={tr("Max messages", "عدد الرسائل")}><NumberInput path="protection.antiSpam.maxMessages" min={2} max={50} /></Field>
          <Field label={tr("Within seconds", "خلال ثواني")}><NumberInput path="protection.antiSpam.perSeconds" min={1} max={60} /></Field>
          <Field label={tr("Action", "العقوبة")}><SelectInput path="protection.antiSpam.action" options={actions(tr)} /></Field>
          <Field label={tr("Timeout minutes", "دقائق الكتم")}><NumberInput path="protection.antiSpam.timeoutMinutes" min={1} max={10080} /></Field>
        </div>
      </Card>
      <Card title="Anti-Link" desc={tr("Block invites from other servers or any links.", "منع روابط السيرفرات أو كل الروابط.")} action={<EnableSwitch path="protection.antiLink.enabled" />}>
        <ToggleRow path="protection.antiLink.blockInvites" label={tr("Block Discord invites", "منع روابط الدعوات")} />
        <ToggleRow path="protection.antiLink.blockAllLinks" label={tr("Block all links", "منع كل الروابط")} />
        <Field label={tr("Allowed channels", "رومات مسموحة")}><ChannelMulti path="protection.antiLink.allowedChannels" /></Field>
      </Card>
      <Card title="Anti-Alt" desc={tr("Minimum Discord account age to join.", "أقل عمر حساب مسموح يدخل.")} action={<EnableSwitch path="protection.antiAlt.enabled" />}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={tr("Minimum age (days)", "أقل عمر (أيام)")}><NumberInput path="protection.antiAlt.minAgeDays" min={1} max={365} /></Field>
          <Field label={tr("Action", "العقوبة")}><SelectInput path="protection.antiAlt.action" options={[{ value: "kick", label: "Kick" }, { value: "ban", label: "Ban" }]} /></Field>
        </div>
      </Card>
      <Card title="Anti-Raid" desc={tr("Detects mass joins and locks the server.", "يكشف دخول جماعي ويقفل السيرفر.")} action={<EnableSwitch path="protection.antiRaid.enabled" />}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={tr("Joins", "عدد الداخلين")}><NumberInput path="protection.antiRaid.joinLimit" min={3} max={100} /></Field>
          <Field label={tr("Within seconds", "خلال ثواني")}><NumberInput path="protection.antiRaid.perSeconds" min={5} max={300} /></Field>
        </div>
      </Card>
      <Card title="Anti-Nuke" desc={tr("Punishes admins who mass-delete channels/roles or mass-ban.", "يعاقب اللي يحذف رومات/رتب أو يبند بشكل جماعي.")} action={<EnableSwitch path="protection.antiNuke.enabled" />}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={tr("Channel deletes", "حذف رومات")}><NumberInput path="protection.antiNuke.channelDeleteLimit" min={1} max={50} /></Field>
          <Field label={tr("Role deletes", "حذف رتب")}><NumberInput path="protection.antiNuke.roleDeleteLimit" min={1} max={50} /></Field>
          <Field label={tr("Bans", "باندات")}><NumberInput path="protection.antiNuke.banLimit" min={1} max={50} /></Field>
          <Field label={tr("Within seconds", "خلال ثواني")}><NumberInput path="protection.antiNuke.perSeconds" min={10} max={3600} /></Field>
          <Field label={tr("Action", "العقوبة")}>
            <SelectInput path="protection.antiNuke.action" options={[{ value: "removeRoles", label: tr("Remove roles", "سحب الرتب") }, { value: "kick", label: "Kick" }, { value: "ban", label: "Ban" }]} />
          </Field>
        </div>
      </Card>
      <Card title={tr("More filters", "فلاتر إضافية")}>
        <ToggleRow path="protection.antiMassMention.enabled" label="Anti Mass-Mention" />
        {s.protection.antiMassMention.enabled && <Field label={tr("Max mentions per message", "أقصى منشن بالرسالة")}><NumberInput path="protection.antiMassMention.limit" min={2} max={50} /></Field>}
        <ToggleRow path="protection.antiBots.enabled" label="Anti-Bot" desc={tr("Kick bots added by non-whitelisted members.", "طرد البوتات اللي يضيفها غير الموثوقين.")} />
        <ToggleRow path="protection.antiWebhook.enabled" label="Anti-Webhook" desc={tr("Delete webhooks created by non-whitelisted members.", "حذف الويب هوك من غير الموثوقين.")} />
        <ToggleRow path="protection.badWords.enabled" label={tr("Bad words filter", "فلتر الكلمات")} />
        {s.protection.badWords.enabled && (
          <textarea
            rows={3}
            className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm"
            value={s.protection.badWords.words.join(", ")}
            onChange={(e) => set("protection.badWords.words", e.target.value.split(",").map((w) => w.trim()).filter(Boolean).slice(0, 300))}
          />
        )}
      </Card>
      <Card title={tr("Whitelist", "القائمة الموثوقة")} desc={tr("These are never punished by protection.", "هدول ما بتطبق عليهم الحماية.")}>
        <Field label={tr("Trusted roles", "رتب موثوقة")}><RoleSelect path="protection.whitelistRoles" /></Field>
        <Field label={tr("Trusted user IDs (comma separated)", "ايديات موثوقة (افصل بفاصلة)")}>
          <input
            className={inputCls}
            value={s.protection.whitelistUsers.join(", ")}
            onChange={(e) => set("protection.whitelistUsers", e.target.value.split(",").map((w) => w.trim()).filter((w) => /^\d+$/.test(w)).slice(0, 100))}
          />
        </Field>
        <Field label={tr("Protection log channel", "روم لوق الحماية")}><ChannelSelect path="logs.channels.protectionLogs" /></Field>
      </Card>
    </div>
  );
}

// ---------------- Logs ----------------
const LOG_LABELS: Record<string, [string, string]> = {
  message: ["Message Logs", "لوق الرسائل"], member: ["Member Logs", "لوق الأعضاء"], voice: ["Voice Logs", "لوق الصوت"],
  moderation: ["Moderation Logs", "لوق الإشراف"], server: ["Server Logs", "لوق السيرفر"], bot: ["PEAK Logs", "لوق البوت"],
};
export function LogsModule() {
  const { tr } = useI18n();
  return (
    <div className="space-y-6">
      <Card title={tr("Logs", "اللوقات")} desc={tr("Pick a channel for every event. Empty uses the default channel.", "اختار روم لكل حدث. الفاضي بروح للروم الافتراضي.")} action={<EnableSwitch path="logs.enabled" />}>
        <Field label={tr("Default log channel", "روم اللوق الافتراضي")}><ChannelSelect path="logs.defaultChannelId" /></Field>
        <Field label={tr("Ignored channels", "رومات متجاهلة")}><ChannelMulti path="logs.ignoredChannels" /></Field>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        {LOG_EVENTS.map((g) => (
          <Card key={g.group} title={tr(LOG_LABELS[g.group]![0], LOG_LABELS[g.group]![1])}>
            {g.keys.map((k) => (
              <div key={k} className="grid items-center gap-2 sm:grid-cols-[160px_1fr]">
                <code className="text-xs text-primary">{k}</code>
                <ChannelSelect path={`logs.channels.${k}`} />
              </div>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}

// ---------------- Levels ----------------
export function LevelsModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const rw = s.levels.rewards;
  return (
    <div className="space-y-6">
      <Card title={tr("Levels & XP", "المستويات و XP")} action={<EnableSwitch path="levels.enabled" />}>
        <div className="grid gap-4 md:grid-cols-3">
          <Field label={tr("Min XP per message", "أقل XP للرسالة")}><NumberInput path="levels.textXpMin" min={1} max={500} /></Field>
          <Field label={tr("Max XP per message", "أعلى XP للرسالة")}><NumberInput path="levels.textXpMax" min={1} max={500} /></Field>
          <Field label={tr("Cooldown (seconds)", "التبريد (ثواني)")}><NumberInput path="levels.cooldownSeconds" min={5} max={3600} /></Field>
        </div>
        <ToggleRow path="levels.voiceEnabled" label={tr("Voice XP", "XP الصوتي")} desc={tr("Members gain XP per minute in voice (not alone, not muted).", "الأعضاء ياخدوا XP كل دقيقة بالصوت.")} />
        {s.levels.voiceEnabled && <Field label={tr("XP per voice minute", "XP لكل دقيقة")}><NumberInput path="levels.voiceXpPerMinute" min={1} max={500} /></Field>}
        <ToggleRow path="levels.announce" label={tr("Announce level ups", "إعلان الصعود")} />
        {s.levels.announce && (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={tr("Level-up channel (empty = same channel)", "روم الإعلان (فاضي = نفس الروم)")}><ChannelSelect path="levels.levelUpChannelId" /></Field>
            <Field label={tr("Message", "الرسالة")} hint="{user} {level}"><TextInput path="levels.levelUpMessage" /></Field>
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={tr("No-XP channels", "رومات بدون XP")}><ChannelMulti path="levels.noXpChannels" /></Field>
          <Field label={tr("No-XP roles", "رتب بدون XP")}><RoleSelect path="levels.noXpRoles" /></Field>
        </div>
      </Card>
      <Card
        title={tr("Level rewards", "رتب المكافآت")}
        action={<Button size="sm" variant="outline" onClick={() => set("levels.rewards", [...rw, { level: 10, roleId: "" }])}><Plus /> {tr("Add", "إضافة")}</Button>}
      >
        <ToggleRow path="levels.stackRewards" label={tr("Keep previous reward roles", "الاحتفاظ بالرتب السابقة")} />
        {rw.map((r, i) => (
          <div key={i} className="grid items-center gap-3 rounded-xl bg-secondary/40 p-3 sm:grid-cols-[140px_1fr_auto]">
            <input type="number" min={1} max={1000} className={inputCls} value={r.level} onChange={(e) => set("levels.rewards", rw.map((x, j) => (j === i ? { ...x, level: Number(e.target.value) || 1 } : x)))} />
            <RoleSelect multi={false} value={r.roleId ? [r.roleId] : []} onChange={(v) => set("levels.rewards", rw.map((x, j) => (j === i ? { ...x, roleId: v[0] ?? "" } : x)))} />
            <Button variant="ghost" size="icon" onClick={() => set("levels.rewards", rw.filter((_, j) => j !== i))}><Trash2 /></Button>
          </div>
        ))}
      </Card>
    </div>
  );
}

// ---------------- Rules ----------------
export function RulesModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const { go, busy } = useSend();
  return (
    <div className="space-y-6">
      <Card
        title={tr("Rules embeds", "قوانين Embed")}
        desc={tr("Build up to 10 embeds and post them together.", "صمم لحد 10 embeds وانشرهم مع بعض.")}
        action={<Button size="sm" variant="hero" disabled={busy} onClick={() => go(s.rules.channelId, { embeds: s.rules.embeds.map((e) => toDiscordEmbed(e)) })}><Send /> {tr("Send", "إرسال")}</Button>}
      >
        <Field label={tr("Rules channel", "روم القوانين")}><ChannelSelect path="rules.channelId" /></Field>
      </Card>
      {s.rules.embeds.map((_, i) => (
        <Card key={i} title={`Embed #${i + 1}`} action={<Button variant="ghost" size="icon" onClick={() => set("rules.embeds", s.rules.embeds.filter((_, j) => j !== i))}><Trash2 /></Button>}>
          <EmbedEditor path={`rules.embeds.${i}`} />
        </Card>
      ))}
      <Button variant="outline" disabled={s.rules.embeds.length >= 10} onClick={() => set("rules.embeds", [...s.rules.embeds, emptyEmbed()])}><Plus /> {tr("Add embed", "إضافة Embed")}</Button>
    </div>
  );
}

// ---------------- Auto Line ----------------
export function AutoLineModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const lines = s.autoLine.lines;
  return (
    <Card
      title={tr("Auto line", "الخط التلقائي")}
      desc={tr("After each message in these channels, PEAK posts the line image/GIF.", "بعد كل رسالة بهالرومات البوت يبعث صورة/GIF الخط.")}
      action={<EnableSwitch path="autoLine.enabled" />}
    >
      <Field label={tr("Per-channel cooldown (seconds)", "تبريد لكل روم (ثواني)")} hint={tr("Minimum 2s to stay within Discord limits.", "أقل شي 2 ثانية عشان قوانين ديسكورد.")}>
        <NumberInput path="autoLine.cooldownSeconds" min={2} max={600} />
      </Field>
      {lines.map((l, i) => (
        <div key={i} className="grid items-center gap-3 rounded-xl bg-secondary/40 p-3 md:grid-cols-[1fr_2fr_auto]">
          <ChannelSelect value={l.channelId} onChange={(v) => set("autoLine.lines", lines.map((x, j) => (j === i ? { ...x, channelId: v } : x)))} />
          <input className={inputCls} placeholder="https://…gif" value={l.imageUrl} onChange={(e) => set("autoLine.lines", lines.map((x, j) => (j === i ? { ...x, imageUrl: e.target.value } : x)))} />
          <Button variant="ghost" size="icon" onClick={() => set("autoLine.lines", lines.filter((_, j) => j !== i))}><Trash2 /></Button>
          {l.imageUrl && <img src={l.imageUrl} alt="" className="max-h-16 rounded md:col-span-3" />}
        </div>
      ))}
      <Button variant="outline" disabled={lines.length >= 25} onClick={() => set("autoLine.lines", [...lines, { channelId: "", imageUrl: "" }])}><Plus /> {tr("Add channel", "إضافة روم")}</Button>
    </Card>
  );
}

// ---------------- Applications ----------------
export function ApplicationsModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const { go, busy } = useSend();
  const forms = s.applications.forms;
  const up = (i: number, patch: Partial<AppForm>) => set("applications.forms", forms.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="space-y-6">
      <Card
        title={tr("Applications", "التقديمات")}
        desc={tr("Members answer up to 5 questions in a form; staff accept or reject in the review channel.", "العضو يجاوب لحد 5 أسئلة بفورم، والإدارة تقبل أو ترفض بروم المراجعة.")}
        action={<EnableSwitch path="applications.enabled" />}
      >
        <Button
          variant="outline"
          disabled={forms.length >= 10}
          onClick={() =>
            set("applications.forms", [
              ...forms,
              { id: uid(), name: "Staff Application", description: "Apply to join our team!", panelChannelId: "", reviewChannelId: "", questions: ["How old are you?", "Why do you want to join?"], acceptRoles: [], buttonLabel: "Apply", open: true, cooldownHours: 24 },
            ])
          }
        >
          <Plus /> {tr("New application", "تقديم جديد")}
        </Button>
      </Card>
      {forms.map((f, i) => (
        <Card
          key={f.id}
          title={f.name || "Application"}
          action={
            <div className="flex items-center gap-2">
              <Switch checked={f.open} onCheckedChange={(v) => up(i, { open: v })} />
              <Button
                size="sm"
                variant="hero"
                disabled={busy}
                onClick={() =>
                  go(f.panelChannelId, {
                    embeds: [toDiscordEmbed(emptyEmbed({ title: f.name, description: f.description, color: s.general.embedColor }))],
                    components: [{ type: 1, components: [{ type: 2, style: 1, label: f.buttonLabel.slice(0, 80) || "Apply", custom_id: `peak:apply:${f.id}` }] }],
                  })
                }
              >
                <Send /> {tr("Send panel", "إرسال")}
              </Button>
              <Button variant="ghost" size="icon" onClick={() => set("applications.forms", forms.filter((_, j) => j !== i))}><Trash2 /></Button>
            </div>
          }
        >
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={tr("Name", "الاسم")}><input className={inputCls} value={f.name} maxLength={45} onChange={(e) => up(i, { name: e.target.value })} /></Field>
            <Field label={tr("Button label", "نص الزر")}><input className={inputCls} value={f.buttonLabel} maxLength={80} onChange={(e) => up(i, { buttonLabel: e.target.value })} /></Field>
            <Field label={tr("Panel channel", "روم التقديم")}><ChannelSelect value={f.panelChannelId} onChange={(v) => up(i, { panelChannelId: v })} /></Field>
            <Field label={tr("Review channel", "روم المراجعة")}><ChannelSelect value={f.reviewChannelId} onChange={(v) => up(i, { reviewChannelId: v })} /></Field>
            <Field label={tr("Roles on accept", "رتب عند القبول")}><RoleSelect value={f.acceptRoles} onChange={(v) => up(i, { acceptRoles: v })} /></Field>
            <Field label={tr("Cooldown between applications (hours)", "مدة بين التقديمات (ساعات)")}>
              <input type="number" min={0} max={720} className={inputCls} value={f.cooldownHours} onChange={(e) => up(i, { cooldownHours: Number(e.target.value) || 0 })} />
            </Field>
          </div>
          <Field label={tr("Description", "الوصف")}>
            <textarea rows={2} className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm" value={f.description} maxLength={2000} onChange={(e) => up(i, { description: e.target.value })} />
          </Field>
          <Field label={tr("Questions (max 5)", "الأسئلة (5 كحد أقصى)")}>
            <div className="space-y-2">
              {f.questions.map((q, qi) => (
                <div key={qi} className="flex gap-2">
                  <input className={inputCls} value={q} maxLength={45} onChange={(e) => up(i, { questions: f.questions.map((x, j) => (j === qi ? e.target.value : x)) })} />
                  <Button variant="ghost" size="icon" onClick={() => up(i, { questions: f.questions.filter((_, j) => j !== qi) })}><Trash2 /></Button>
                </div>
              ))}
              <Button size="sm" variant="outline" disabled={f.questions.length >= 5} onClick={() => up(i, { questions: [...f.questions, ""] })}><Plus /></Button>
            </div>
          </Field>
        </Card>
      ))}
    </div>
  );
}


function TicketDmPreview() {
  const { s } = useDash();
  const { tr } = useI18n();
  const rows: [string, string][] = [
    ["📄", tr("Ticket number", "رقم التذكرة")],
    ["👑", tr("Ticket staff", "مشرفين التذكرة")],
    ["🛡️", tr("Claimed by", "مسؤول التذكرة")],
    ["📅", tr("Opened at", "وقت التذكرة")],
  ];
  return (
    <div className="max-w-md rounded-md border-s-4 border-primary bg-secondary/40 p-4 text-sm">
      <div className="mb-2 font-semibold">🎟️ | {tr("Ticket attachments", "مرفقات التذكرة")}</div>
      <div className="mb-3">💛 : {s.tickets.dmOnClose.message}</div>
      {rows.map(([e, l]) => (
        <div key={l} className="mb-2"><div className="font-medium">{e} : {l}</div><div className="text-muted-foreground">…</div></div>
      ))}
      {s.tickets.dmOnClose.sendTranscript && <div className="mt-2 rounded bg-background/60 px-3 py-2 text-xs">📁 transcript-ticket-0001.txt</div>}
    </div>
  );
}

// ---------------- Games ----------------
export function GamesModule() {
  const { s, set } = useDash();
  const { tr, lang } = useI18n();
  const { go, busy } = useSend();
  const [panelCh, setPanelCh] = useState("");
  const kinds: { k: string; en: string; ar: string }[] = [
    { k: "server", en: "Server games (everyone joins)", ar: "ألعاب السيرفر (الكل يشارك)" },
    { k: "duel", en: "1 vs 1", ar: "واحد ضد واحد" },
    { k: "mini", en: "Mini games (first right answer wins)", ar: "ألعاب سريعة (أول جواب صح يفوز)" },
  ];
  const on = GAMES.filter((x) => s.games.list[x.id] !== false);
  const panel = () =>
    go(panelCh, {
      embeds: [toDiscordEmbed(emptyEmbed({ title: "🎮 PEAK Games", description: tr("Pick a game from the list to start it in this channel.", "اختار لعبة من القائمة عشان تبدأ بهالروم."), color: s.general.embedColor }))],
      components: [
        {
          type: 1,
          components: [
            {
              type: 3,
              custom_id: "peak:games:panel",
              placeholder: tr("Choose a game", "اختار لعبة"),
              options: on.slice(0, 25).map((x) => ({ label: lang === "ar" ? x.ar : x.en, value: x.id, emoji: { name: x.emoji } })),
            },
          ],
        },
      ],
    });
  return (
    <div className="space-y-6">
      <Card
        title={tr("Games", "الألعاب")}
        desc={tr(`Start with /play or ${s.games.prefix}roulette, ${s.games.prefix}mafia … Winners earn coins in the bank.`, `ابدأ بـ /play أو ${s.games.prefix}روليت، ${s.games.prefix}مافيا … والفايز ياخد كوينز بالبنك.`)}
        action={<EnableSwitch path="games.enabled" />}
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={tr("Games prefix", "بادئة الألعاب")} hint={tr("Example: - (so -roulette)", "مثال: - (يعني -روليت)")}><TextInput path="games.prefix" maxLength={3} /></Field>
          <Field label={tr("Join time (seconds)", "وقت الانضمام (ثواني)")}><NumberInput path="games.lobbySeconds" min={15} max={120} /></Field>
          <Field label={tr("Max players", "أقصى عدد لاعبين")}><NumberInput path="games.maxPlayers" min={4} max={25} /></Field>
          <Field label={tr("Coins for the winner", "كوينز للفايز")}><NumberInput path="games.winnerCoins" min={0} max={100000} /></Field>
          <Field label={tr("Coins for a mini game", "كوينز للعبة السريعة")}><NumberInput path="games.miniCoins" min={0} max={100000} /></Field>
        </div>
        <Field label={tr("Game channels (empty = all channels)", "رومات الألعاب (فاضي = كل الرومات)")}><ChannelMulti path="games.channels" kind="text" /></Field>
        <Field label={tr("Who can start/stop games (empty = everyone)", "مين يقدر يبدأ ويوقف الألعاب (فاضي = الكل)")}><RoleSelect path="games.managerRoles" /></Field>
      </Card>
      {kinds.map((k) => (
        <Card key={k.k} title={tr(k.en, k.ar)}>
          <div className="grid gap-3 md:grid-cols-2">
            {GAMES.filter((x) => x.kind === k.k).map((x) => (
              <div key={x.id} className="flex items-center gap-3 rounded-xl bg-secondary/40 p-3">
                <span className="text-xl">{x.emoji}</span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{lang === "ar" ? x.ar : x.en}</div>
                  <code className="text-xs text-primary">{s.games.prefix}{x.ar}</code> <code className="text-xs text-muted-foreground">{s.games.prefix}{x.id}</code>
                </div>
                <Switch checked={s.games.list[x.id] !== false} onCheckedChange={(v) => set(`games.list.${x.id}`, v)} />
              </div>
            ))}
          </div>
        </Card>
      ))}
      <Card title={tr("Games menu", "قائمة الألعاب")} desc={tr("Send a menu members can pick a game from.", "ابعت قائمة يختار منها الأعضاء اللعبة.")} action={<Button size="sm" variant="hero" disabled={busy} onClick={panel}><Send /> {tr("Send menu", "إرسال القائمة")}</Button>}>
        <ChannelSelect value={panelCh} onChange={setPanelCh} />
      </Card>
    </div>
  );
}

// ---------------- Bank ----------------
export function BankModule() {
  const { s } = useDash();
  const { tr } = useI18n();
  const { go, busy } = useSend();
  const [panelCh, setPanelCh] = useState("");
  const b = s.bank;
  const btn = (id: string, label: string, emoji: string, style = 2) => ({ type: 2, style, label, custom_id: `peak:bank:${id}`, emoji: { name: emoji } });
  const panel = () =>
    go(panelCh, {
      embeds: [toDiscordEmbed(emptyEmbed({ title: `🏦 ${tr("PEAK Bank", "بنك PEAK")}`, description: tr("Use the buttons below to manage your money.", "استخدم الأزرار تحت عشان تدير فلوسك."), color: s.general.embedColor }))],
      components: [
        { type: 1, components: [btn("balance", tr("Balance", "رصيدي"), "💰", 1), btn("daily", tr("Daily", "يومي"), "🎁", 3), btn("work", tr("Work", "راتب"), "💼")] },
        { type: 1, components: [btn("deposit", tr("Deposit", "إيداع"), "📥"), btn("withdraw", tr("Withdraw", "سحب"), "📤"), btn("transfer", tr("Transfer", "تحويل"), "💸"), btn("top", tr("Richest", "الأغنى"), "🏆")] },
      ],
    });
  const cmds: [string, string, string][] = [
    ["رصيد / balance", tr("Wallet and bank balance", "رصيد المحفظة والبنك"), ""],
    ["يومي / daily", tr("Daily reward", "الهدية اليومية"), `${b.dailyAmount} ${b.currencyEmoji}`],
    ["راتب / work", tr("Work for coins", "اشتغل وخذ راتب"), `${b.workMin}-${b.workMax} ${b.currencyEmoji}`],
    ["تحويل / transfer @user 100", tr("Send coins", "حوّل لشخص"), `${b.transferTax}%`],
    ["ايداع / deposit 100", tr("Wallet → bank (safe from robbers)", "من المحفظة للبنك (محمي من السرقة)"), ""],
    ["سحب / withdraw 100", tr("Bank → wallet", "من البنك للمحفظة"), ""],
    ["نهب / rob @user", tr("Try to rob a wallet", "حاول تسرق محفظة"), `${b.rob.chance}%`],
    ["قمار / bet 100", tr("Double or nothing", "يا بتضاعف يا بتخسر"), ""],
    ["سلوت / slots 100", tr("Slot machine", "آلة الحظ"), ""],
    ["وجه / coinflip 100", tr("Heads or tails", "ملك ولا كتابة"), ""],
    ["الاغنى / rich", tr("Richest members", "أغنى الأعضاء"), ""],
    ["اعطاء / give @user 100", tr("Admins: add or remove coins (use -100)", "للإدارة: إضافة أو سحب (استخدم -100)"), ""],
  ];
  return (
    <div className="space-y-6">
      <Card title={tr("Bank", "البنك")} desc={tr(`Commands use the bot prefix (${s.general.prefix}) or slash commands. Every server has its own bank.`, `الأوامر بالبادئة (${s.general.prefix}) أو أوامر السلاش. كل سيرفر إله بنك لحاله.`)} action={<EnableSwitch path="bank.enabled" />}>
        <div className="grid gap-4 md:grid-cols-3">
          <Field label={tr("Currency name", "اسم العملة")}><TextInput path="bank.currencyName" maxLength={20} /></Field>
          <Field label={tr("Currency emoji", "ايموجي العملة")}><TextInput path="bank.currencyEmoji" maxLength={40} /></Field>
          <Field label={tr("Starting balance", "الرصيد الابتدائي")}><NumberInput path="bank.startBalance" min={0} max={1000000} /></Field>
          <Field label={tr("Daily reward", "الهدية اليومية")}><NumberInput path="bank.dailyAmount" min={0} max={1000000} /></Field>
          <Field label={tr("Work: minimum", "الراتب: أقل شي")}><NumberInput path="bank.workMin" min={0} max={1000000} /></Field>
          <Field label={tr("Work: maximum", "الراتب: أعلى شي")}><NumberInput path="bank.workMax" min={0} max={1000000} /></Field>
          <Field label={tr("Work cooldown (minutes)", "وقت بين الرواتب (دقائق)")}><NumberInput path="bank.workCooldownMinutes" min={1} max={1440} /></Field>
          <Field label={tr("Transfer tax %", "ضريبة التحويل %")}><NumberInput path="bank.transferTax" min={0} max={50} /></Field>
        </div>
        <Field label={tr("Bank channels (empty = all channels)", "رومات البنك (فاضي = كل الرومات)")}><ChannelMulti path="bank.channels" kind="text" /></Field>
        <Field label={tr("Bank admin roles (can give/take coins)", "رتب إدارة البنك (تعطي وتسحب)")}><RoleSelect path="bank.adminRoles" /></Field>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={tr("Robbing", "النهب")} action={<EnableSwitch path="bank.rob.enabled" />}>
          <div className="grid grid-cols-2 gap-3">
            <Field label={tr("Success chance %", "نسبة النجاح %")}><NumberInput path="bank.rob.chance" min={1} max={90} /></Field>
            <Field label={tr("Max stolen % of wallet", "أقصى نسبة تنسرق %")}><NumberInput path="bank.rob.maxPercent" min={1} max={100} /></Field>
            <Field label={tr("Cooldown (minutes)", "وقت الانتظار (دقائق)")}><NumberInput path="bank.rob.cooldownMinutes" min={5} max={1440} /></Field>
            <Field label={tr("Fine when caught %", "الغرامة لو انمسك %")}><NumberInput path="bank.rob.fine" min={0} max={100} /></Field>
          </div>
        </Card>
        <Card title={tr("Gambling", "القمار والحظ")} action={<EnableSwitch path="bank.gamble.enabled" />}>
          <Field label={tr("Max bet", "أقصى رهان")}><NumberInput path="bank.gamble.maxBet" min={1} max={100000000} /></Field>
        </Card>
        <Card title={tr("Daily bank interest", "فائدة البنك اليومية")} desc={tr("Paid on money kept in the bank, once a day.", "تنضاف على الفلوس اللي بالبنك، مرة باليوم.")} action={<EnableSwitch path="bank.interest.enabled" />}>
          <Field label={tr("Interest %", "الفائدة %")}><NumberInput path="bank.interest.percent" min={1} max={10} /></Field>
        </Card>
        <Card title={tr("Bank menu", "قائمة البنك")} desc={tr("Send buttons members can use instead of typing commands.", "ابعت أزرار يستخدمها الأعضاء بدل ما يكتبوا أوامر.")} action={<Button size="sm" variant="hero" disabled={busy} onClick={panel}><Send /> {tr("Send menu", "إرسال القائمة")}</Button>}>
          <ChannelSelect value={panelCh} onChange={setPanelCh} />
        </Card>
      </div>
      <Card title={tr("Bank commands", "أوامر البنك")}>
        <div className="grid gap-2 md:grid-cols-2">
          {cmds.map(([c, d, x]) => (
            <div key={c} className="rounded-xl bg-secondary/40 p-3 text-sm">
              <code className="text-primary">{s.general.prefix}{c}</code>
              <div className="text-muted-foreground">{d} {x && <span className="text-foreground">· {x}</span>}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
