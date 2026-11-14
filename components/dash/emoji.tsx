import { useState } from "react";
import { Smile, X } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useDash, type GuildEmoji } from "./fields";
import { useI18n } from "@/lib/i18n";

// Emojis are stored as text: a normal emoji ("🔥") or a server emoji ("<:name:id>" / "<a:name:id>").
const CUSTOM_RE = /^<(a?):([\w~]{1,32}):(\d{5,25})>$/;

export function customEmojiUrl(v: string) {
  const m = CUSTOM_RE.exec((v ?? "").trim());
  return m ? `https://cdn.discordapp.com/emojis/${m[3]}.${m[1] ? "gif" : "png"}?size=48` : null;
}

export function emojiText(e: GuildEmoji) {
  return `<${e.animated ? "a" : ""}:${e.name}:${e.id}>`;
}

export function EmojiView({ value, className = "h-5 w-5" }: { value: string; className?: string }) {
  const url = customEmojiUrl(value);
  if (url) return <img src={url} alt="" className={`${className} inline-block object-contain`} />;
  return <span className="inline-flex items-center justify-center leading-none">{value}</span>;
}

const GROUPS: { en: string; ar: string; list: string }[] = [
  { en: "Popular", ar: "الأكثر استخداماً", list: "✅ ❌ ⭐ 🔥 ❤️ 👍 👎 👏 🎉 😂 😍 🥰 😎 🤔 😢 😡 💯 👀 🙏 💪 🤝 👑 💎 🏆 🎁 📢 📌 ⚡ ✨ 💥" },
  { en: "Faces", ar: "وجوه", list: "😀 😃 😄 😁 😆 😅 🤣 😊 😇 🙂 😉 😌 😋 😛 😜 🤪 🤗 🤭 🤫 😏 😴 🥳 🤩 😬 🙄 😮 😱 😤 🥺 😭 🤯 🥶 🥵 😈 👻 💀 🤖 👽 🤡 💩" },
  { en: "Hearts", ar: "قلوب", list: "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝" },
  { en: "Hands", ar: "أيادي", list: "👋 🤚 ✋ 🖐️ 👌 🤌 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👊 ✊ 🙌 🫶 🫡" },
  { en: "Games", ar: "ألعاب", list: "🎮 🕹️ 🎲 🎯 🎳 🃏 ♟️ 🧩 🎰 ⚽ 🏀 🏈 ⚾ 🎾 🏐 🏓 🥊 🏁 🚩 🎨 🎵 🎶 🎧 🎤 📸 🎬" },
  { en: "Symbols", ar: "رموز", list: "🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪ 🟤 🔺 🔻 ⬆️ ⬇️ ➡️ ⬅️ 🔁 🔔 🔕 🔒 🔓 🛡️ ⚔️ 🗡️ 💣 📣 💬 💭 🆕 🆗 🆒 🔞 ⚠️ ⛔ 🚫 ♻️ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣" },
  { en: "Nature & food", ar: "طبيعة وأكل", list: "🌙 ☀️ ⭐ 🌈 ❄️ 🌊 🌹 🌸 🌻 🍀 🌴 🐶 🐱 🦁 🐺 🦅 🐍 🐉 🍎 🍕 🍔 🍟 🍩 🍰 ☕ 🧋" },
  { en: "Flags", ar: "أعلام", list: "🇯🇴 🇸🇦 🇵🇸 🇪🇬 🇦🇪 🇰🇼 🇶🇦 🇧🇭 🇴🇲 🇮🇶 🇸🇾 🇱🇧 🇲🇦 🇩🇿 🇹🇳 🇾🇪 🇺🇸 🇬🇧 🇹🇷" },
];

function Grid({ onPick }: { onPick: (v: string) => void }) {
  const { emojis } = useDash();
  const { tr } = useI18n();
  const [custom, setCustom] = useState("");
  return (
    <div className="max-h-80 space-y-3 overflow-y-auto p-3">
      <div className="flex gap-2">
        <input
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder={tr("Paste any emoji or <:name:id>", "الصق أي إيموجي أو <:name:id>")}
          className="h-8 w-full rounded-md border border-input bg-background/60 px-2 text-xs"
        />
        <button
          type="button"
          className="rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
          disabled={!custom.trim()}
          onClick={() => { onPick(custom.trim().slice(0, 80)); setCustom(""); }}
        >
          {tr("Add", "إضافة")}
        </button>
      </div>
      {emojis.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">{tr("Server emojis", "إيموجيات السيرفر")}</div>
          <div className="grid grid-cols-8 gap-1">
            {emojis.slice(0, 400).map((e) => (
              <button key={e.id} type="button" title={`:${e.name}:`} onClick={() => onPick(emojiText(e))} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-secondary">
                <EmojiView value={emojiText(e)} className="h-6 w-6" />
              </button>
            ))}
          </div>
        </div>
      )}
      {GROUPS.map((g) => (
        <div key={g.en}>
          <div className="mb-1 text-xs font-medium text-muted-foreground">{tr(g.en, g.ar)}</div>
          <div className="grid grid-cols-8 gap-1">
            {g.list.split(" ").filter(Boolean).map((e, i) => (
              <button key={`${e}-${i}`} type="button" onClick={() => onPick(e)} className="flex h-8 w-8 items-center justify-center rounded-md text-lg hover:bg-secondary">
                {e}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** One emoji, chosen from the server's emojis or the common list. */
export function EmojiPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="flex h-9 w-14 shrink-0 items-center justify-center rounded-md border border-input bg-background/60 text-lg">
          {value ? <EmojiView value={value} className="h-6 w-6" /> : <Smile className="h-4 w-4 opacity-60" />}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0">
        <Grid onPick={(v) => { onChange(v); setOpen(false); }} />
      </PopoverContent>
    </Popover>
  );
}

/** Several emojis (e.g. auto reactions), in order. */
export function EmojiMulti({ value, onChange, max = 5 }: { value: string[]; onChange: (v: string[]) => void; max?: number }) {
  const { tr } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background/60 px-2 py-1.5">
      {value.map((v, i) => (
        <span key={`${v}-${i}`} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-1 text-base">
          <EmojiView value={v} />
          <X className="h-3 w-3 cursor-pointer opacity-70" onClick={() => onChange(value.filter((_, j) => j !== i))} />
        </span>
      ))}
      {value.length < max && (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button type="button" className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary">
              <Smile className="h-4 w-4" /> {tr("Pick emoji", "اختار إيموجي")}
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-80 p-0">
            <Grid onPick={(v) => { if (!value.includes(v)) onChange([...value, v].slice(0, max)); setOpen(false); }} />
          </PopoverContent>
        </Popover>
      )}
      <span className="ms-auto text-xs text-muted-foreground">{value.length}/{max}</span>
    </div>
  );
}
