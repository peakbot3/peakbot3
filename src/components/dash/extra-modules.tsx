import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { Image as ImageIcon, Info, Loader2, Plus, RotateCcw, Send, Smile, Sparkles, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { sendReactionRolePanel, sendToChannel, setBotServerAvatar } from "@/lib/api.functions";
import { useI18n } from "@/lib/i18n";
import { TEMP_VOICE_BUTTONS, emptyEmbed, type AutoReactRule, type AutoReplyItem, type ReactionRolePanel } from "@/lib/settings";
import { DiscordMessage, EmbedEditor } from "./embed";
import { EmojiMulti, EmojiPicker, EmojiView, customEmojiUrl } from "./emoji";
import {
  Card, ChannelSelect, EnableSwitch, Field, NumberInput, RoleSelect, TextInput, ToggleRow, roleColor, setPath, useDash,
} from "./fields";
import mark from "@/assets/peak-mark.png";

const uid = () => Math.random().toString(36).slice(2, 10);
const inputCls = "h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm";

/** Writes a value the website already saved (e.g. a posted message id) without marking the page as changed. */
function useSavedSet() {
  const { set, guild } = useDash();
  const qc = useQueryClient();
  return (path: string, value: unknown) => {
    const cached = qc.getQueryData(["guild", guild.id]) as { settings?: unknown } | undefined;
    if (cached?.settings) cached.settings = setPath(cached.settings, path, value);
    set(path, value);
  };
}

function Empty({ icon: Icon, title, desc, action }: { icon: typeof Smile; title: string; desc: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border p-10 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-secondary"><Icon className="h-6 w-6 text-muted-foreground" /></div>
      <div className="font-semibold">{title}</div>
      <div className="max-w-md text-sm text-muted-foreground">{desc}</div>
      {action}
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl border border-primary/30 bg-primary/10 p-4 text-sm">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Count({ n, label }: { n: number; label: string }) {
  return <span className="rounded-md border border-border bg-secondary/60 px-2 py-1 text-xs">{n} {label}</span>;
}

// ---------------- Reaction roles ----------------
export function ReactionRolesModule() {
  const { s, set, roles, dirty, guild } = useDash();
  const { tr } = useI18n();
  const send = useServerFn(sendReactionRolePanel);
  const savedSet = useSavedSet();
  const [busy, setBusy] = useState<string | null>(null);
  const panels = s.reactionRoles.panels;
  const up = (i: number, patch: Partial<ReactionRolePanel>) => set("reactionRoles.panels", panels.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  const post = async (i: number) => {
    const p = panels[i]!;
    if (dirty) { toast.error(tr("Save your changes first, then send.", "احفظ التغييرات أول، وبعدين ابعت.")); return; }
    setBusy(p.id);
    try {
      const r = await send({ data: { guildId: guild.id, panelId: p.id } });
      savedSet(`reactionRoles.panels.${i}.messageId`, r.messageId);
      toast.success(tr("Message sent — members can pick their roles now.", "انبعتت الرسالة — الأعضاء بقدروا ياخدوا رتبهم هلأ."));
    } catch (e) {
      toast.error((e as Error).message);
    }
    setBusy(null);
  };

  const writeList = (i: number) => {
    const p = panels[i]!;
    const lines = p.items.filter((it) => it.emoji && it.roleId).map((it) => `${it.emoji} ➜ <@&${it.roleId}>${it.label ? ` — ${it.label}` : ""}`);
    up(i, { embed: { ...p.embed, description: [p.embed.description.split("\n\n")[0] || tr("Pick your roles below.", "اختار رتبك من تحت."), lines.join("\n")].filter(Boolean).join("\n\n") } });
  };

  const roleName = (id: string) => roles.find((r) => r.id === id);
  const addPanel = () =>
    set("reactionRoles.panels", [
      ...panels,
      {
        id: uid(), channelId: "", messageId: "", mode: "reactions", unique: false,
        embed: emptyEmbed({ title: tr("🎭 Pick your roles", "🎭 اختار رتبك"), description: tr("Click an emoji below to get its role. Click again to remove it.", "اضغط على إيموجي تحت عشان تاخد الرتبة. اضغط مرة ثانية عشان تشيلها."), color: s.general.embedColor }),
        items: [],
      } satisfies ReactionRolePanel,
    ]);

  return (
    <div className="space-y-6">
      <Card
        title={tr("Emoji roles", "رتب بالإيموجي")}
        desc={tr("PEAK posts a message in the channel you pick. Whoever clicks an emoji (or button) under it gets that role.", "البوت بيبعت رسالة بالروم اللي بتختاره، واللي بكبس على الإيموجي (أو الزر) تحتها بياخد الرتبة.")}
        action={<EnableSwitch path="reactionRoles.enabled" />}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Count n={panels.length} label={tr("messages", "رسائل")} />
          <Button size="sm" variant="outline" disabled={panels.length >= 15} onClick={addPanel}><Plus /> {tr("New role message", "رسالة رتب جديدة")}</Button>
        </div>
        {panels.length === 0 && (
          <Empty
            icon={Smile}
            title={tr("No role messages yet", "لا يوجد رسائل رتب بعد")}
            desc={tr("Add a message, pick emojis and their roles, save, then send it.", "ضيف رسالة، اختار الإيموجيات ورتبها، احفظ، وبعدين ابعتها.")}
            action={<Button size="sm" variant="outline" onClick={addPanel}><Plus /> {tr("Create the first message", "إنشاء أول رسالة")}</Button>}
          />
        )}
        <Note>
          <div>{tr("PEAK's role must be above the roles it gives (Server Settings → Roles).", "لازم رتبة البوت تكون فوق الرتب اللي بيعطيها (إعدادات السيرفر ← الرتب).")}</div>
        </Note>
      </Card>

      {panels.map((p, i) => (
        <Card
          key={p.id}
          title={p.embed.title || tr(`Role message #${i + 1}`, `رسالة رتب #${i + 1}`)}
          desc={p.messageId ? tr("✅ Posted. Sending again updates the same message.", "✅ انبعتت. الإرسال مرة ثانية بيحدّث نفس الرسالة.") : tr("Not posted yet.", "لسا ما انبعتت.")}
          action={
            <div className="flex items-center gap-2">
              <Button size="sm" variant="hero" disabled={busy === p.id} onClick={() => post(i)}>
                {busy === p.id ? <Loader2 className="animate-spin" /> : <Send />} {p.messageId ? tr("Update", "تحديث") : tr("Send", "إرسال")}
              </Button>
              <Button variant="ghost" size="icon" onClick={() => set("reactionRoles.panels", panels.filter((_, j) => j !== i))}><Trash2 /></Button>
            </div>
          }
        >
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={tr("Channel", "الروم")}><ChannelSelect value={p.channelId} onChange={(v) => up(i, { channelId: v })} /></Field>
            <Field label={tr("Members click on", "الأعضاء بكبسوا على")}>
              <select className={inputCls} value={p.mode} onChange={(e) => up(i, { mode: e.target.value as ReactionRolePanel["mode"] })}>
                <option value="reactions">{tr("Emoji reactions under the message", "رياكشن إيموجي تحت الرسالة")}</option>
                <option value="buttons">{tr("Buttons with emoji", "أزرار فيها إيموجي")}</option>
              </select>
            </Field>
          </div>
          <div className="flex items-center justify-between gap-4 rounded-xl bg-secondary/40 p-4">
            <div>
              <div className="font-medium">{tr("Only one role from this message", "رتبة وحدة بس من هالرسالة")}</div>
              <div className="text-xs text-muted-foreground">{tr("Picking a new one removes the old one (e.g. colors, age).", "لما ياخد وحدة جديدة بتنشال القديمة (مثلاً الألوان، العمر).")}</div>
            </div>
            <Switch checked={p.unique} onCheckedChange={(v) => up(i, { unique: v })} />
          </div>

          <Field label={tr("Emojis and roles", "الإيموجيات والرتب")}>
            <div className="space-y-2">
              {p.items.map((it, k) => (
                <div key={k} className="flex flex-wrap items-center gap-2 rounded-xl bg-secondary/40 p-2 md:flex-nowrap">
                  <EmojiPicker value={it.emoji} onChange={(v) => up(i, { items: p.items.map((x, j) => (j === k ? { ...x, emoji: v } : x)) })} />
                  <div className="min-w-48 flex-1"><RoleSelect multi={false} value={it.roleId ? [it.roleId] : []} onChange={(v) => up(i, { items: p.items.map((x, j) => (j === k ? { ...x, roleId: v[0] ?? "" } : x)) })} /></div>
                  <input className={`${inputCls} md:w-56`} maxLength={80} placeholder={tr("Label (optional)", "وصف (اختياري)")} value={it.label} onChange={(e) => up(i, { items: p.items.map((x, j) => (j === k ? { ...x, label: e.target.value } : x)) })} />
                  <Button variant="ghost" size="icon" onClick={() => up(i, { items: p.items.filter((_, j) => j !== k) })}><Trash2 /></Button>
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={p.items.length >= 20} onClick={() => up(i, { items: [...p.items, { emoji: "", roleId: "", label: "" }] })}><Plus /> {tr("Add emoji", "إضافة إيموجي")}</Button>
                <Button size="sm" variant="ghost" disabled={!p.items.length} onClick={() => writeList(i)}><Sparkles /> {tr("Write the list in the message", "اكتب القائمة بالرسالة")}</Button>
              </div>
            </div>
          </Field>

          <EmbedEditor path={`reactionRoles.panels.${i}.embed`} />
          <div>
            <div className="mb-2 text-sm text-muted-foreground">{tr("Under the message", "تحت الرسالة")}</div>
            {p.mode === "reactions" ? (
              <div className="flex flex-wrap gap-1.5">
                {p.items.filter((x) => x.emoji).map((x, k) => (
                  <span key={k} className="inline-flex items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 text-sm"><EmojiView value={x.emoji} className="h-4 w-4" /> 1</span>
                ))}
              </div>
            ) : (
              <div className="flex max-w-md flex-wrap gap-1.5">
                {p.items.filter((x) => x.emoji).map((x, k) => {
                  const r = roleName(x.roleId);
                  return (
                    <span key={k} className="inline-flex items-center gap-1.5 rounded-md bg-secondary px-3 py-1.5 text-sm">
                      <EmojiView value={x.emoji} className="h-4 w-4" />
                      <span style={r ? { color: roleColor(r.color) } : undefined}>{x.label || r?.name || ""}</span>
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}

// ---------------- Auto react ----------------
export function AutoReactModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const rules = s.autoReact.rules;
  const up = (i: number, patch: Partial<AutoReactRule>) => set("autoReact.rules", rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => set("autoReact.rules", [...rules, { id: uid(), channels: [], emojis: ["❤️"], onlyImages: false } satisfies AutoReactRule]);
  return (
    <div className="space-y-6">
      <Card
        title={tr("Auto emoji", "الإيموجي التلقائي")}
        desc={tr("PEAK reacts with emojis on every new message in the channels you pick, to boost activity.", "البوت بيحط تفاعل إيموجي تلقائي على كل رسالة جديدة بالرومات اللي بتختارها لزيادة التفاعل.")}
      >
        <ToggleRow path="autoReact.enabled" label={tr("Turn on auto emoji", "تفعيل الإيموجي التلقائي")} desc={tr("When on, PEAK reacts to new messages using the rules below.", "عند التفعيل البوت بيتفاعل تلقائياً على الرسائل الجديدة حسب القواعد تحت.")} />
      </Card>
      <Card
        title={tr("Reaction rules", "قواعد التفاعل التلقائي")}
        desc={tr("Each rule: which channels, and which emojis (up to 5).", "كل قاعدة: أي رومات، وأي إيموجيات (لحد 5).")}
        action={
          <div className="flex items-center gap-2">
            <Count n={rules.length} label={tr("rules", "قواعد")} />
            <Button size="sm" variant="outline" disabled={rules.length >= 10} onClick={add}><Plus /> {tr("Add emoji rule", "إضافة قاعدة إيموجي")}</Button>
          </div>
        }
      >
        {rules.length === 0 && (
          <Empty
            icon={Smile}
            title={tr("No auto emoji rules yet", "لا توجد قواعد إيموجي تلقائية بعد")}
            desc={tr("Press the button to add your first rule and pick its channels and emojis.", "اضغط على الزر لإضافة أول قاعدة وتحديد القنوات والإيموجيات.")}
            action={<Button size="sm" variant="outline" onClick={add}><Plus /> {tr("Create the first rule", "إنشاء أول قاعدة")}</Button>}
          />
        )}
        {rules.map((r, i) => (
          <div key={r.id} className="space-y-3 rounded-xl bg-secondary/40 p-4">
            <div className="flex items-center justify-between">
              <div className="font-medium">{tr(`Rule #${i + 1}`, `قاعدة #${i + 1}`)}</div>
              <Button variant="ghost" size="icon" onClick={() => set("autoReact.rules", rules.filter((_, j) => j !== i))}><Trash2 /></Button>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label={tr("Channels", "الرومات")}><ChannelMultiValue value={r.channels} onChange={(v) => up(i, { channels: v })} /></Field>
              <Field label={tr("Emojis", "الإيموجيات")}><EmojiMulti value={r.emojis} onChange={(v) => up(i, { emojis: v })} /></Field>
            </div>
            <div className="flex items-center justify-between gap-4">
              <div className="text-sm">{tr("Only messages with a picture or file", "بس الرسائل اللي فيها صورة أو ملف")}</div>
              <Switch checked={r.onlyImages} onCheckedChange={(v) => up(i, { onlyImages: v })} />
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

/** Channel multi-select bound to a value (not a settings path). */
function ChannelMultiValue({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { channels } = useDash();
  const { tr } = useI18n();
  const text = channels.filter((c) => c.type === 0 || c.type === 5);
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background/60 px-2 py-1.5">
      {value.map((id) => (
        <span key={id} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-sm">
          # {text.find((c) => c.id === id)?.name ?? id}
          <button type="button" className="opacity-70" onClick={() => onChange(value.filter((v) => v !== id))}>×</button>
        </span>
      ))}
      <select className="h-7 min-w-32 flex-1 bg-transparent text-sm text-muted-foreground" value="" onChange={(e) => e.target.value && onChange([...value, e.target.value].slice(0, 25))}>
        <option value="">{tr("+ Add channel", "+ إضافة روم")}</option>
        {text.filter((c) => !value.includes(c.id)).map((c) => <option key={c.id} value={c.id}># {c.name}</option>)}
      </select>
    </div>
  );
}

// ---------------- Temp voice ----------------
export function tempVoicePanelPayload(s: ReturnType<typeof useDash>["s"], imageUrl: string) {
  const em = (v: string) => {
    const m = /^<(a?):([\w~]{1,32}):(\d{5,25})>$/.exec(v.trim());
    return m ? { id: m[3], name: m[2], animated: m[1] === "a" } : { name: v || "▫️" };
  };
  const btns = TEMP_VOICE_BUTTONS.map((b) => ({ type: 2, style: 2, custom_id: `peak:tv:${b.id}`, emoji: em(s.tempVoice.buttonEmojis[b.id] || b.emoji) }));
  return {
    embeds: [
      {
        title: "Interface - لوحة التحكم",
        description:
          "This interface can be used to manage temporary voice channels.\nيمكن استخدام لوحة التحكم لإدارة القنوات الصوتية المؤقتة.",
        color: 0xed4245,
        image: { url: imageUrl },
        footer: { text: "Press the buttons below to use the interface.\nاضغط على الأزرار أدناه لاستخدام لوحة التحكم." },
      },
    ],
    components: [0, 5, 10].map((r) => ({ type: 1, components: btns.slice(r, r + 5) })),
  };
}

export function TempVoiceModule() {
  const { s, set } = useDash();
  const { tr, lang } = useI18n();
  const send = useServerFn(sendToChannel);
  const [busy, setBusy] = useState(false);
  const tv = s.tempVoice;
  const image = /^https?:\/\//.test(tv.panelImage) ? tv.panelImage : typeof window !== "undefined" ? `${window.location.origin}/tempvoice-interface.png` : "/tempvoice-interface.png";
  const { guild } = useDash();
  const postPanel = async () => {
    if (!tv.panelChannelId) { toast.error(tr("Pick the panel channel first", "اختار روم اللوحة أول")); return; }
    setBusy(true);
    try {
      await send({ data: { guildId: guild.id, channelId: tv.panelChannelId, ...tempVoicePanelPayload(s, image) } as never });
      toast.success(tr("Panel sent", "انبعتت اللوحة"));
    } catch (e) {
      toast.error((e as Error).message);
    }
    setBusy(false);
  };
  const vars = ["{username}", "{nick}", "{count}"];
  return (
    <div className="space-y-6">
      <Card
        title={tr("Temp voice rooms", "الرومات الصوتية المؤقتة (Temp Voice)")}
        desc={tr("Members join one voice channel and PEAK creates their own room, then deletes it when it's empty.", "العضو بيدخل روم صوتي واحد والبوت بيعمله روم خاص فيه، وبينحذف تلقائياً لما يفضى.")}
        action={<EnableSwitch path="tempVoice.enabled" />}
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={tr("Join to create channel", "روم الانضمام (Join to Create)")} hint={tr("Joining this voice channel creates a new room.", "لما حدا يدخل هالروم الصوتي بينعمله روم جديد.")}>
            <ChannelSelect path="tempVoice.joinChannelId" kind="voice" />
          </Field>
          <Field label={tr("Category for the rooms (optional)", "تصنيف الرومات (اختياري)")} hint={tr("Empty = same category as the join channel.", "فاضي = نفس تصنيف روم الانضمام.")}>
            <ChannelSelect path="tempVoice.categoryId" kind="category" />
          </Field>
          <Field label={tr("Room name", "قالب اسم الروم")}>
            <TextInput path="tempVoice.nameTemplate" maxLength={90} />
            <div className="flex flex-wrap gap-1.5 text-xs">
              {vars.map((v) => (
                <button key={v} type="button" onClick={() => set("tempVoice.nameTemplate", `${tv.nameTemplate}${v}`.slice(0, 90))} className="rounded border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-primary">{v}</button>
              ))}
            </div>
          </Field>
          <Field label={tr("Default member limit (0 = no limit)", "الحد الافتراضي للأعضاء (0 = بدون حد)")}><NumberInput path="tempVoice.defaultLimit" max={99} /></Field>
        </div>
        <Note>
          <div className="font-medium">{tr("How it works", "كيف يعمل")}</div>
          <div>• {tr("A member joins the join-to-create channel.", "العضو بيدخل روم الانضمام.")}</div>
          <div>• {tr("PEAK creates a room with their name and moves them into it.", "البوت بيعمله روم باسمه وبينقله عليه فوراً.")}</div>
          <div>• {tr("The owner controls it with the panel buttons.", "صاحب الروم بيتحكم فيه من أزرار اللوحة.")}</div>
          <div>• {tr("When everyone leaves, the room is deleted.", "لما الكل يطلع، الروم بينحذف تلقائياً.")}</div>
        </Note>
      </Card>

      <Card title={tr("Control panel", "لوحة التحكم")} desc={tr("The panel image with 15 buttons, like the picture below.", "صورة اللوحة مع 15 زر، زي الصورة تحت.")}>
        <ToggleRow path="tempVoice.panelInVoiceChat" label={tr("Send the panel in the room's chat", "إرسال لوحة التحكم في شات الروم الصوتي")} desc={tr("Every new room gets the panel in its text chat.", "كل روم جديد بتنبعتله اللوحة بالشات تبعه.")} />
        <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
          <Field label={tr("Fixed panel in a text channel (optional)", "لوحة تحكم في روم كتابي (اختياري)")} hint={tr("Buttons there control the room the member is in.", "الأزرار هناك بتتحكم بالروم اللي العضو فيه.")}>
            <ChannelSelect path="tempVoice.panelChannelId" />
          </Field>
          <Button variant="hero" disabled={busy} onClick={postPanel}>{busy ? <Loader2 className="animate-spin" /> : <Send />} {tr("Send panel", "نشر اللوحة")}</Button>
        </div>
        <Field label={tr("Panel image link (optional)", "رابط صورة اللوحة (اختياري)")} hint={tr("Empty = the built-in buttons image.", "فاضي = صورة الأزرار الجاهزة.")}>
          <TextInput path="tempVoice.panelImage" placeholder="https://…" />
        </Field>
        <Field label={tr("Button emojis", "إيموجيات الأزرار")} hint={tr("Tip: upload the icons as server emojis and pick them here for the exact look.", "نصيحة: ارفع الأيقونات كإيموجيات بالسيرفر واختارها هون عشان يطلع الشكل نفسه بالضبط.")}>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {TEMP_VOICE_BUTTONS.map((b) => (
              <div key={b.id} className="flex items-center gap-2 rounded-xl bg-secondary/40 p-2">
                <EmojiPicker value={tv.buttonEmojis[b.id] || b.emoji} onChange={(v) => set(`tempVoice.buttonEmojis.${b.id}`, v)} />
                <span className="truncate text-xs font-semibold uppercase">{lang === "ar" ? b.ar : b.en}</span>
              </div>
            ))}
          </div>
        </Field>
        <div>
          <div className="mb-2 text-sm text-muted-foreground">{tr("How it looks", "شكلها بالديسكورد")}</div>
          <TempVoicePreview image={image} />
        </div>
      </Card>
    </div>
  );
}

function TempVoicePreview({ image }: { image: string }) {
  const { s } = useDash();
  return (
    <div className="flex gap-3 rounded-xl bg-embed p-4 text-sm">
      <img src={mark} alt="" className="h-10 w-10 rounded-full bg-background object-contain p-1" />
      <div className="min-w-0 max-w-xl flex-1">
        <div className="flex items-center gap-2"><span className="font-semibold">PEAK</span><span className="rounded bg-discord px-1 text-[10px] font-bold">APP</span></div>
        <div className="mt-2 overflow-hidden rounded border-s-4 border-destructive bg-background/50 p-4">
          <div className="text-xl font-bold">Interface - لوحة التحكم</div>
          <div className="mt-2 text-muted-foreground">This interface can be used to manage temporary voice channels.</div>
          <div className="text-muted-foreground" dir="rtl">يمكن استخدام لوحة التحكم لإدارة القنوات الصوتية المؤقتة.</div>
          <img src={image} alt="" className="mt-3 w-full rounded" />
          <div className="mt-3 text-xs">Press the buttons below to use the interface.</div>
          <div className="text-xs" dir="rtl">اضغط على الأزرار أدناه لاستخدام لوحة التحكم.</div>
        </div>
        <div className="mt-2 grid max-w-sm grid-cols-5 gap-1.5">
          {TEMP_VOICE_BUTTONS.map((b) => {
            const v = s.tempVoice.buttonEmojis[b.id] || b.emoji;
            return (
              <span key={b.id} title={b.en} className="flex h-9 items-center justify-center rounded-md bg-secondary text-lg">
                {customEmojiUrl(v) ? <EmojiView value={v} className="h-5 w-5" /> : v}
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------- Auto reply ----------------
export function AutoReplyModule() {
  const { s, set } = useDash();
  const { tr } = useI18n();
  const list = s.autoReply.replies;
  const up = (i: number, patch: Partial<AutoReplyItem>) => set("autoReply.replies", list.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () =>
    set("autoReply.replies", [
      ...list,
      { id: uid(), triggers: [tr("hello", "السلام عليكم")], match: "exact", response: tr("Hello {user} 👋", "وعليكم السلام {user} 👋"), asReply: true, asEmbed: false, channels: [], enabled: true } satisfies AutoReplyItem,
    ]);
  const matchLabel = (m: AutoReplyItem["match"]) => (m === "exact" ? tr("Exact", "مطابق") : m === "contains" ? tr("Contains", "يحتوي") : tr("Starts with", "يبدأ بـ"));
  return (
    <div className="space-y-6">
      <Card
        title={tr("Auto reply", "الرد التلقائي")}
        desc={tr("When someone writes a trigger word, PEAK answers with your reply.", "لما حدا يكتب كلمة معينة، البوت بيرد بالرد اللي بتحطه.")}
        action={<EnableSwitch path="autoReply.enabled" />}
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={tr("Wait between replies in a channel (seconds)", "وقت بين الردود بنفس الروم (ثواني)")}><NumberInput path="autoReply.cooldownSeconds" min={2} max={600} /></Field>
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {["{user}", "{username}", "{server}", "{memberCount}"].map((v) => <code key={v} className="rounded bg-secondary px-1.5 py-0.5 text-primary">{v}</code>)}
        </div>
      </Card>

      <Card
        title={tr("Replies list", "قائمة الردود")}
        action={
          <div className="flex items-center gap-2">
            <Count n={list.length} label={tr("replies", "ردود")} />
            <Button size="sm" variant="outline" disabled={list.length >= 50} onClick={add}><Plus /> {tr("Add reply", "إضافة رد")}</Button>
          </div>
        }
      >
        {list.length === 0 && (
          <Empty icon={Smile} title={tr("No replies yet", "ما في ردود لسا")} desc={tr("Add a trigger word and what PEAK should answer.", "ضيف كلمة والرد اللي البوت لازم يرد فيه.")} action={<Button size="sm" variant="outline" onClick={add}><Plus /> {tr("Add the first reply", "إضافة أول رد")}</Button>} />
        )}
        {list.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-secondary/60 text-xs text-muted-foreground">
                <tr>
                  <th className="p-2 text-start">#</th>
                  <th className="p-2 text-start">{tr("Trigger", "الكلمة")}</th>
                  <th className="p-2 text-start">{tr("Match", "المطابقة")}</th>
                  <th className="p-2 text-start">{tr("Reply", "الرد")}</th>
                  <th className="p-2 text-start">{tr("On", "مفعّل")}</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r, i) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="p-2 text-muted-foreground">{i + 1}</td>
                    <td className="max-w-40 truncate p-2 font-medium">{r.triggers.join("، ")}</td>
                    <td className="p-2">{matchLabel(r.match)}</td>
                    <td className="max-w-64 truncate p-2 text-muted-foreground">{r.response}</td>
                    <td className="p-2"><Switch checked={r.enabled} onCheckedChange={(v) => up(i, { enabled: v })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.map((r, i) => (
          <div key={r.id} className="space-y-3 rounded-xl bg-secondary/40 p-4">
            <div className="flex items-center justify-between">
              <div className="font-medium">{tr(`Reply #${i + 1}`, `رد #${i + 1}`)}</div>
              <Button variant="ghost" size="icon" onClick={() => set("autoReply.replies", list.filter((_, j) => j !== i))}><Trash2 /></Button>
            </div>
            <div className="grid gap-3 md:grid-cols-[2fr_1fr]">
              <Field label={tr("Trigger words (comma separated)", "الكلمات (افصل بفاصلة)")}>
                <input
                  className={inputCls}
                  defaultValue={r.triggers.join(", ")}
                  onBlur={(e) => up(i, { triggers: e.target.value.split(/[,،]/).map((x) => x.trim()).filter(Boolean).slice(0, 10) })}
                />
              </Field>
              <Field label={tr("Match", "المطابقة")}>
                <select className={inputCls} value={r.match} onChange={(e) => up(i, { match: e.target.value as AutoReplyItem["match"] })}>
                  <option value="exact">{tr("Exact message", "الرسالة نفسها بالضبط")}</option>
                  <option value="contains">{tr("Message contains it", "الرسالة فيها الكلمة")}</option>
                  <option value="startsWith">{tr("Message starts with it", "الرسالة بتبدأ فيها")}</option>
                </select>
              </Field>
            </div>
            <Field label={tr("Reply", "الرد")}>
              <textarea rows={2} maxLength={2000} className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm" value={r.response} onChange={(e) => up(i, { response: e.target.value })} />
            </Field>
            <Field label={tr("Only in these channels (empty = all)", "بس بهالرومات (فاضي = الكل)")}><ChannelMultiValue value={r.channels} onChange={(v) => up(i, { channels: v })} /></Field>
            <div className="grid gap-2 md:grid-cols-2">
              <div className="flex items-center justify-between gap-3 rounded-lg bg-background/40 p-3 text-sm">{tr("Reply to the message", "رد على الرسالة نفسها")}<Switch checked={r.asReply} onCheckedChange={(v) => up(i, { asReply: v })} /></div>
              <div className="flex items-center justify-between gap-3 rounded-lg bg-background/40 p-3 text-sm">{tr("Send as embed", "إرسال كـ Embed")}<Switch checked={r.asEmbed} onCheckedChange={(v) => up(i, { asEmbed: v })} /></div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

// ---------------- Punishment DMs ----------------
export function ModDmModule() {
  const { s, guild } = useDash();
  const { tr } = useI18n();
  const rows: { k: "warn" | "timeout" | "kick" | "ban"; en: string; ar: string }[] = [
    { k: "warn", en: "Warn", ar: "تحذير (وارن)" },
    { k: "timeout", en: "Timeout", ar: "تايم أوت (كتم)" },
    { k: "kick", en: "Kick", ar: "طرد" },
    { k: "ban", en: "Ban", ar: "باند" },
  ];
  const fill = (t: string) => t.replaceAll("{server}", guild.name).replaceAll("{duration}", "10m").replaceAll("{reason}", tr("Spam", "سبام")).replaceAll("{moderator}", "@Admin");
  return (
    <div className="space-y-6">
      <Card
        title={tr("Private message on punishment", "رسالة خاصة عند العقوبة")}
        desc={tr("When staff warn, timeout, kick or ban someone with PEAK's commands, the member gets a private message (e.g. \"You got warned\").", "لما الإدارة تعطي وارن أو تايم أوت أو طرد أو باند بأوامر البوت، العضو بتوصله رسالة عالخاص (مثلاً \"You got warned\").")}
        action={<EnableSwitch path="modDm.enabled" />}
      >
        <ToggleRow path="modDm.showModerator" label={tr("Show who punished them", "إظهار مين عاقبه")} />
        <div className="flex flex-wrap gap-1.5 text-xs">
          {["{server}", "{reason}", "{moderator}", "{duration}"].map((v) => <code key={v} className="rounded bg-secondary px-1.5 py-0.5 text-primary">{v}</code>)}
        </div>
        {rows.map((r) => (
          <div key={r.k} className="grid items-center gap-3 rounded-xl bg-secondary/40 p-3 md:grid-cols-[160px_1fr_auto]">
            <div className="font-medium">{tr(r.en, r.ar)}</div>
            <TextInput path={`modDm.${r.k}.message`} maxLength={500} />
            <EnableSwitch path={`modDm.${r.k}.enabled`} />
          </div>
        ))}
        <Note>{tr("The message is sent before a kick or ban, so it still reaches the member.", "الرسالة بتنبعت قبل الطرد أو الباند عشان توصل للعضو.")}</Note>
      </Card>
      <Card title={tr("Preview", "معاينة")}>
        <DiscordMessage
          embed={emptyEmbed({
            title: fill(s.modDm.warn.message),
            description: `**${tr("Reason", "السبب")}:** ${tr("Spam", "سبام")}${s.modDm.showModerator ? `\n**${tr("By", "من")}:** @Admin` : ""}`,
            color: "#f59e0b",
            footer: guild.name,
          })}
        />
      </Card>
    </div>
  );
}

// ---------------- Bot profile (this server only) ----------------
export function BotProfileModule() {
  const { s, guild } = useDash();
  const { tr } = useI18n();
  const setAvatar = useServerFn(setBotServerAvatar);
  const savedSet = useSavedSet();
  const [busy, setBusy] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const avatar = s.general.botAvatar || mark;
  const name = s.general.nickname || "PEAK";

  const run = async (kind: "upload" | "serverIcon" | "reset", dataUri?: string) => {
    setBusy(kind);
    try {
      const r = await setAvatar({ data: { guildId: guild.id, kind, ...(dataUri ? { dataUri } : {}) } });
      savedSet("general.botAvatar", r.url);
      toast.success(tr("Bot picture updated in this server.", "تغيرت صورة البوت بهالسيرفر."));
    } catch (e) {
      toast.error((e as Error).message);
    }
    setBusy(null);
  };

  const onFile = (f: File | undefined) => {
    if (!f) return;
    if (!/^image\/(png|jpeg|gif|webp)$/.test(f.type)) { toast.error(tr("Use a PNG, JPG, GIF or WEBP picture.", "استخدم صورة PNG أو JPG أو GIF أو WEBP.")); return; }
    if (f.size > 4 * 1024 * 1024) { toast.error(tr("The picture must be smaller than 4 MB.", "لازم الصورة تكون أقل من 4 ميغا.")); return; }
    const reader = new FileReader();
    reader.onload = () => run("upload", String(reader.result));
    reader.readAsDataURL(f);
  };

  return (
    <div className="space-y-6">
      <Card title={tr("Linked server", "السيرفر المرتبط")} action={<span className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-xs text-primary">{tr("This server only", "تخصيص جزئي")}</span>}>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl bg-secondary/40 p-4"><div className="text-xs text-muted-foreground">{tr("Server name", "اسم السيرفر")}</div><div className="mt-1 font-semibold">{guild.name}</div></div>
          <div className="rounded-xl bg-secondary/40 p-4"><div className="text-xs text-muted-foreground">{tr("Bot status", "حالة البوت")}</div><div className="mt-1 font-semibold text-primary">● {tr("Connected and ready", "متصل وجاهز")}</div></div>
        </div>
        <Note>{tr("The name and picture change only in this server. Other servers keep PEAK's normal name and picture.", "الاسم والصورة بيتغيروا بهالسيرفر بس. باقي السيرفرات بيضل فيها اسم وصورة البوت العادية.")}</Note>
      </Card>

      <Card title={tr("Bot name and picture in this server", "تخصيص اسم وهوية البوت في السيرفر")}>
        <div className="flex items-center gap-4 rounded-xl bg-secondary/40 p-4">
          <img src={avatar} alt="" className="h-14 w-14 rounded-full bg-background object-cover" />
          <div>
            <div className="flex items-center gap-2"><span className="font-semibold">{name}</span><span className="rounded bg-discord px-1.5 text-[10px] font-bold">✓ BOT</span></div>
            <div className="text-xs text-muted-foreground">{guild.name}</div>
          </div>
        </div>
        <div className="space-y-3 rounded-xl bg-secondary/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="font-medium">{tr("Bot picture in this server (Avatar)", "صورة البوت في السيرفر (Avatar)")}</div>
            <div className="text-xs text-muted-foreground">{tr("Applied right away", "بتتطبق فوراً")}</div>
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden" onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="hero" disabled={!!busy} onClick={() => fileRef.current?.click()}>{busy === "upload" ? <Loader2 className="animate-spin" /> : <Upload />} {tr("Upload a new picture", "رفع صورة مخصصة جديدة")}</Button>
            <Button size="sm" variant="outline" disabled={!!busy || !guild.icon} onClick={() => run("serverIcon")}>{busy === "serverIcon" ? <Loader2 className="animate-spin" /> : <ImageIcon />} {tr("Use the server icon", "وضع شعار السيرفر كأيقونة")}</Button>
            <Button size="sm" variant="outline" disabled={!!busy || !s.general.botAvatar} onClick={() => run("reset")}>{busy === "reset" ? <Loader2 className="animate-spin" /> : <RotateCcw />} {tr("Back to the normal picture", "استعادة الصورة الافتراضية")}</Button>
          </div>
        </div>
        <Field label={tr("Bot name in this server (Nickname)", "اسم البوت المستقل داخل السيرفر (Nickname)")} hint={tr("Press Save changes to apply the name.", "اضغط حفظ التغييرات عشان يتطبق الاسم.")}>
          <TextInput path="general.nickname" maxLength={32} placeholder="PEAK" />
        </Field>
      </Card>
    </div>
  );
}

// ---------------- Games list command (added to the Games tab) ----------------
export function GamesListCard() {
  const { s } = useDash();
  const { tr } = useI18n();
  const p = s.games.prefix || "-";
  return (
    <Card title={tr("Games list & bank commands", "قائمة الألعاب وأوامر البنك")} desc={tr("Two quick commands for members.", "أمرين سريعين للأعضاء.")}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl bg-secondary/40 p-3 text-sm">
          <code className="text-primary">{p}games</code> · <code className="text-primary">{p}العاب</code>
          <div className="text-muted-foreground">{tr("Sends the list of games (with a picture if you add one) and a menu to start one.", "بيبعت قائمة الألعاب (مع صورة إذا حطيت) وقائمة تختار منها لعبة.")}</div>
        </div>
        <div className="rounded-xl bg-secondary/40 p-3 text-sm">
          <code className="text-primary">{p}اوامر</code> · <code className="text-primary">{p}commands</code>
          <div className="text-muted-foreground">{tr("Sends all bank commands so people know how to use it (needs the bank on).", "بيبعت كل أوامر البنك عشان الناس تعرف (لازم البنك يكون مفعّل).")}</div>
        </div>
      </div>
      <Field label={tr("Games list picture (optional)", "صورة قائمة الألعاب (اختياري)")} hint={tr("A picture link shown with the games list.", "رابط صورة بتطلع مع قائمة الألعاب.")}>
        <TextInput path="games.listImage" placeholder="https://…" />
      </Field>
      {/^https?:\/\//.test(s.games.listImage) && <img src={s.games.listImage} alt="" className="max-h-48 rounded-lg" />}
    </Card>
  );
}

