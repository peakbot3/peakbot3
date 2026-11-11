import { Link, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useRef, useState } from "react";
import { Languages, LogOut, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import mark from "@/assets/peak-mark.png";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { adminLogin, getSessionInfo, logout } from "@/lib/api.functions";
import { useI18n } from "@/lib/i18n";

export const sessionQuery = { queryKey: ["session"], queryFn: () => getSessionInfo() };

export function avatarUrl(u: { id: string; avatar: string | null }) {
  return u.avatar ? `https://cdn.discordapp.com/avatars/${u.id}/${u.avatar}.png?size=64` : "https://cdn.discordapp.com/embed/avatars/0.png";
}

export function openDiscordLogin() {
  // On the real site, sign in in the same tab so the dashboard shows your servers right after login.
  let framed = false;
  try {
    framed = window.top !== window.self;
  } catch {
    framed = true;
  }
  if (!framed) {
    window.location.href = "/api/auth/discord/login";
    return;
  }
  // Discord's sign-in page cannot load inside a frame (editor preview), so open a new tab there.
  const w = window.open("/api/auth/discord/login", "_blank");
  if (!w) window.location.href = "/api/auth/discord/login";
}

export function SiteHeader() {
  const { t, lang, setLang } = useI18n();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery(sessionQuery);
  const clicks = useRef<number[]>([]);
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const login = useServerFn(adminLogin);
  const doLogout = useServerFn(logout);

  const onLogoClick = (e: React.MouseEvent) => {
    const now = Date.now();
    clicks.current = [...clicks.current.filter((c) => now - c < 2500), now];
    if (clicks.current.length >= 5) {
      e.preventDefault();
      clicks.current = [];
      if (data?.admin) navigate({ to: "/admin" });
      else setOpen(true);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const r = await login({ data: { id, password: pw } }).catch(() => ({ ok: false }));
    setBusy(false);
    if (!r.ok) { toast.error(t("wrong")); return; }
    setOpen(false);
    setPw("");
    await qc.invalidateQueries({ queryKey: ["session"] });
    navigate({ to: "/admin" });
  };

  return (
    <header className="sticky top-0 z-40 glass border-x-0 border-t-0">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
        <Link to="/" onClick={onLogoClick} className="flex select-none items-center gap-2">
          <img src={mark} alt="" className="h-9 w-9 object-contain drop-shadow-[0_0_8px_var(--neon)]" />
          <span className="font-display text-2xl font-bold tracking-widest neon-text">PEAK</span>
        </Link>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setLang(lang === "en" ? "ar" : "en")}>
            <Languages className="h-4 w-4" /> {lang === "en" ? "العربية" : "English"}
          </Button>
          {data?.admin && (
            <Button variant="ghost" size="sm" asChild>
              <Link to="/admin"><ShieldCheck className="h-4 w-4" /> {t("adminPanel")}</Link>
            </Button>
          )}
          {data?.user ? (
            <div className="flex items-center gap-2">
              <img src={avatarUrl(data.user)} alt="" className="h-8 w-8 rounded-full ring-2 ring-primary/50" />
              <span className="hidden text-sm sm:inline">{data.user.global_name ?? data.user.username}</span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("logout")}
                onClick={async () => {
                  await doLogout();
                  await qc.invalidateQueries();
                  navigate({ to: "/" });
                }}
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            data?.loginReady && <Button size="sm" variant="outline" onClick={openDiscordLogin}>{t("login")}</Button>
          )}
        </div>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="glass">
          <DialogHeader><DialogTitle className="font-display">{t("adminLogin")}</DialogTitle></DialogHeader>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2"><Label>{t("discordId")}</Label><Input value={id} onChange={(e) => setId(e.target.value)} autoComplete="username" /></div>
            <div className="space-y-2"><Label>{t("password")}</Label><Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></div>
            <Button type="submit" className="w-full" disabled={busy}>{t("signIn")}</Button>
          </form>
        </DialogContent>
      </Dialog>
    </header>
  );
}
