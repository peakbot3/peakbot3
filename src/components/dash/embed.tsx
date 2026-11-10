import type { ReactNode } from "react";
import mark from "@/assets/peak-mark.png";
import type { Embed } from "@/lib/settings";
import { fillVars } from "@/lib/settings";
import { Field, getPath, useDash } from "./fields";

export function toDiscordEmbed(e: Embed, vars?: Parameters<typeof fillVars>[1]) {
  const f = (s: string) => (vars ? fillVars(s, vars) : s);
  const out: Record<string, unknown> = {};
  if (e.title) out["title"] = f(e.title).slice(0, 256);
  if (e.description) out["description"] = f(e.description).slice(0, 4096);
  out["color"] = parseInt((e.color || "#22d3ee").replace("#", ""), 16) || 0;
  if (/^https?:\/\//.test(e.imageUrl)) out["image"] = { url: e.imageUrl };
  if (/^https?:\/\//.test(e.thumbnailUrl)) out["thumbnail"] = { url: e.thumbnailUrl };
  if (e.footer) out["footer"] = { text: f(e.footer) };
  if (e.authorName) out["author"] = { name: f(e.authorName) };
  return out;
}

function md(text: string) {
  // tiny Discord-markdown preview: **bold**, newlines
  return text.split("\n").map((line, i) => (
    <span key={i}>
      {line.split(/(\*\*[^*]+\*\*)/g).map((p, j) => (p.startsWith("**") ? <b key={j}>{p.slice(2, -2)}</b> : p))}
      <br />
    </span>
  ));
}

export function DiscordMessage({ content, embed, children }: { content?: string; embed?: Embed | null; children?: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl bg-embed p-4 text-sm">
      <img src={mark} alt="" className="h-10 w-10 rounded-full bg-background object-contain p-1" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold">PEAK</span>
          <span className="rounded bg-discord px-1 text-[10px] font-bold">APP</span>
        </div>
        {content && <div className="mt-1 whitespace-pre-wrap">{md(content)}</div>}
        {embed && (embed.title || embed.description || embed.imageUrl) && (
          <div className="mt-2 max-w-md overflow-hidden rounded border-s-4 bg-background/50 p-3" style={{ borderInlineStartColor: embed.color }}>
            <div className="flex gap-3">
              <div className="min-w-0 flex-1">
                {embed.authorName && <div className="mb-1 text-xs font-semibold">{embed.authorName}</div>}
                {embed.title && <div className="mb-1 font-semibold">{embed.title}</div>}
                {embed.description && <div className="text-muted-foreground">{md(embed.description)}</div>}
              </div>
              {embed.thumbnailUrl && <img src={embed.thumbnailUrl} alt="" className="h-16 w-16 rounded object-cover" />}
            </div>
            {embed.imageUrl && <img src={embed.imageUrl} alt="" className="mt-3 max-h-64 w-full rounded object-cover" />}
            {embed.footer && <div className="mt-2 text-xs text-muted-foreground">{embed.footer}</div>}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

const inputCls = "h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm";
export function EmbedEditor({ path }: { path: string }) {
  const { s, set } = useDash();
  const e = getPath(s, path) as Embed;
  const up = (k: keyof Embed, v: string) => set(`${path}.${k}`, v);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-3">
        <Field label="Author"><input className={inputCls} value={e.authorName} onChange={(x) => up("authorName", x.target.value)} maxLength={256} /></Field>
        <Field label="Title"><input className={inputCls} value={e.title} onChange={(x) => up("title", x.target.value)} maxLength={256} /></Field>
        <Field label="Description">
          <textarea rows={5} className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm" value={e.description} onChange={(x) => up("description", x.target.value)} maxLength={4096} />
        </Field>
        <div className="grid grid-cols-[auto_1fr] gap-3">
          <Field label="Color"><input type="color" className="h-9 w-14 rounded-md border border-input bg-transparent" value={e.color} onChange={(x) => up("color", x.target.value)} /></Field>
          <Field label="Footer"><input className={inputCls} value={e.footer} onChange={(x) => up("footer", x.target.value)} maxLength={2048} /></Field>
        </div>
        <Field label="Image URL"><input className={inputCls} value={e.imageUrl} onChange={(x) => up("imageUrl", x.target.value)} placeholder="https://…" /></Field>
        <Field label="Thumbnail URL"><input className={inputCls} value={e.thumbnailUrl} onChange={(x) => up("thumbnailUrl", x.target.value)} placeholder="https://…" /></Field>
      </div>
      <div><DiscordMessage embed={e} /></div>
    </div>
  );
}
