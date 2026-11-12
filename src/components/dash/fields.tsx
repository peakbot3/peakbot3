import { createContext, useContext, useState, type ReactNode } from "react";
import { Check, ChevronsUpDown, Hash, Volume2, Folder, X } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import type { Settings } from "@/lib/settings";
import { useI18n } from "@/lib/i18n";

export type Channel = { id: string; name: string; type: number; parentId: string | null };
export type Role = { id: string; name: string; color: number; managed: boolean };
export type GuildEmoji = { id: string; name: string; animated: boolean };

type Ctx = {
  s: Settings;
  set: (path: string, value: unknown) => void;
  channels: Channel[];
  roles: Role[];
  emojis: GuildEmoji[];
  guild: { id: string; name: string; icon: string | null; memberCount: number };
  /** True while the page has changes that are not saved yet. */
  dirty?: boolean;
};
export const DashCtx = createContext<Ctx>(null as unknown as Ctx);
export const useDash = () => useContext(DashCtx);

export function setPath<T>(obj: T, path: string, value: unknown): T {
  const keys = path.split(".");
  const clone = structuredClone(obj) as Record<string, unknown>;
  let cur: Record<string, unknown> = clone;
  keys.slice(0, -1).forEach((k) => {
    cur[k] = cur[k] && typeof cur[k] === "object" ? cur[k] : {};
    cur = cur[k] as Record<string, unknown>;
  });
  cur[keys[keys.length - 1]!] = value;
  return clone as T;
}
export function getPath(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], obj);
}

export function Card({ title, desc, children, action }: { title: string; desc?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="glass space-y-5 rounded-2xl p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          {desc && <p className="mt-1 text-sm text-muted-foreground">{desc}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function ToggleRow({ path, label, desc }: { path: string; label: string; desc?: string }) {
  const { s, set } = useDash();
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl bg-secondary/40 p-4">
      <div>
        <div className="font-medium">{label}</div>
        {desc && <div className="text-xs text-muted-foreground">{desc}</div>}
      </div>
      <Switch checked={!!getPath(s, path)} onCheckedChange={(v) => set(path, v)} />
    </div>
  );
}

export function EnableSwitch({ path }: { path: string }) {
  const { s, set } = useDash();
  return <Switch checked={!!getPath(s, path)} onCheckedChange={(v) => set(path, v)} />;
}

function chIcon(type: number) {
  return type === 2 || type === 13 ? Volume2 : type === 4 ? Folder : Hash;
}

type PickerItem = { id: string; label: string; color?: string | undefined; icon?: typeof Hash | undefined };

function Picker({ items, value, onChange, multi, placeholder }: { items: PickerItem[]; value: string[]; onChange: (v: string[]) => void; multi?: boolean; placeholder?: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const selected = items.filter((i) => value.includes(i.id));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-background/60 px-3 py-1.5 text-start text-sm">
          {selected.length === 0 && <span className="text-muted-foreground">{placeholder ?? t("select")}</span>}
          {selected.map((i) => {
            const Icon = i.icon;
            return (
              <span key={i.id} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5" style={i.color ? { color: i.color } : undefined}>
                {Icon && <Icon className="h-3 w-3" />}
                {i.label}
                {multi && (
                  <X className="h-3 w-3 cursor-pointer opacity-70" onClick={(e) => { e.stopPropagation(); onChange(value.filter((v) => v !== i.id)); }} />
                )}
              </span>
            );
          })}
          <ChevronsUpDown className="ms-auto h-4 w-4 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] min-w-64 p-0">
        <Command>
          <CommandInput placeholder="Search…" />
          <CommandList>
            <CommandEmpty>—</CommandEmpty>
            <CommandGroup>
              {!multi && (
                <CommandItem onSelect={() => { onChange([]); setOpen(false); }}>{t("none")}</CommandItem>
              )}
              {items.map((i) => {
                const Icon = i.icon;
                const on = value.includes(i.id);
                return (
                  <CommandItem
                    key={i.id}
                    value={`${i.label} ${i.id}`}
                    onSelect={() => {
                      if (multi) onChange(on ? value.filter((v) => v !== i.id) : [...value, i.id]);
                      else { onChange([i.id]); setOpen(false); }
                    }}
                  >
                    <Check className={`h-4 w-4 ${on ? "opacity-100" : "opacity-0"}`} />
                    {Icon && <Icon className="h-4 w-4 opacity-60" />}
                    <span style={i.color ? { color: i.color } : undefined}>{i.label}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export type ChannelKind = "text" | "voice" | "category" | "any";
export function useChannelItems(kind: ChannelKind) {
  const { channels } = useDash();
  return channels
    .filter((c) =>
      kind === "any" ? c.type !== 4 : kind === "text" ? c.type === 0 || c.type === 5 : kind === "voice" ? c.type === 2 || c.type === 13 : c.type === 4,
    )
    .map((c) => ({ id: c.id, label: c.name, icon: chIcon(c.type) }));
}

export function ChannelSelect({ path, kind = "text", value, onChange }: { path?: string; kind?: ChannelKind; value?: string; onChange?: (v: string) => void }) {
  const { s, set } = useDash();
  const items = useChannelItems(kind);
  const v = path ? String(getPath(s, path) ?? "") : value ?? "";
  return <Picker items={items} value={v ? [v] : []} onChange={(a) => (path ? set(path, a[0] ?? "") : onChange?.(a[0] ?? ""))} />;
}

export function ChannelMulti({ path, kind = "any" }: { path: string; kind?: ChannelKind }) {
  const { s, set } = useDash();
  const items = useChannelItems(kind);
  return <Picker multi items={items} value={(getPath(s, path) as string[]) ?? []} onChange={(a) => set(path, a)} />;
}

export function roleColor(c: number) {
  return c ? `#${c.toString(16).padStart(6, "0")}` : undefined;
}
export function RoleSelect({ path, multi = true, value, onChange }: { path?: string; multi?: boolean; value?: string[]; onChange?: (v: string[]) => void }) {
  const { s, set, roles } = useDash();
  const items = roles.filter((r) => !r.managed).map((r) => ({ id: r.id, label: `@${r.name}`, color: roleColor(r.color) }));
  const v = path ? ((getPath(s, path) as string[] | string) ?? []) : value ?? [];
  const arr = Array.isArray(v) ? v : v ? [v] : [];
  return (
    <Picker
      multi={multi}
      items={items}
      value={arr}
      onChange={(a) => (path ? set(path, multi ? a : a[0] ?? "") : onChange?.(a))}
    />
  );
}

export function NumberInput({ path, min = 0, max = 100000 }: { path: string; min?: number; max?: number }) {
  const { s, set } = useDash();
  return (
    <input
      type="number"
      min={min}
      max={max}
      value={Number(getPath(s, path) ?? 0)}
      onChange={(e) => set(path, Math.max(min, Math.min(max, Number(e.target.value) || 0)))}
      className="h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm"
    />
  );
}

export function TextInput({ path, placeholder, maxLength = 2000 }: { path: string; placeholder?: string; maxLength?: number }) {
  const { s, set } = useDash();
  return (
    <input
      value={String(getPath(s, path) ?? "")}
      maxLength={maxLength}
      placeholder={placeholder}
      onChange={(e) => set(path, e.target.value)}
      className="h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm"
    />
  );
}

export function TextArea({ path, rows = 4, maxLength = 4000 }: { path: string; rows?: number; maxLength?: number }) {
  const { s, set } = useDash();
  return (
    <textarea
      rows={rows}
      maxLength={maxLength}
      value={String(getPath(s, path) ?? "")}
      onChange={(e) => set(path, e.target.value)}
      className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm"
    />
  );
}

export function SelectInput({ path, options }: { path: string; options: { value: string; label: string }[] }) {
  const { s, set } = useDash();
  return (
    <select
      value={String(getPath(s, path) ?? "")}
      onChange={(e) => set(path, e.target.value)}
      className="h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

export function VarHint() {
  return (
    <div className="flex flex-wrap gap-1.5 text-xs">
      {["{user}", "{username}", "{server}", "{memberCount}"].map((v) => (
        <code key={v} className="rounded bg-secondary px-1.5 py-0.5 text-primary">{v}</code>
      ))}
    </div>
  );
}
