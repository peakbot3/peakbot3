import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { openDiscordLogin, sessionQuery } from "@/components/SiteHeader";
import { listMyGuilds } from "@/lib/api.functions";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/dashboard/")({
  head: () => ({
    meta: [
      { title: "Your Servers — PEAK Dashboard" },
      { name: "description", content: "Pick a Discord server you manage to configure PEAK." },
      { property: "og:title", content: "Your Servers — PEAK Dashboard" },
      { property: "og:description", content: "Pick a Discord server you manage to configure PEAK." },
    ],
  }),
  component: Servers,
});

export function guildIcon(g: { id: string; icon: string | null; name: string }) {
  return g.icon ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=128` : null;
}

export function GuildAvatar({ g, size = "h-16 w-16" }: { g: { id: string; icon: string | null; name: string }; size?: string }) {
  const src = guildIcon(g);
  return src ? (
    <img src={src} alt="" className={`${size} rounded-2xl`} />
  ) : (
    <div className={`${size} flex items-center justify-center rounded-2xl bg-secondary font-display text-xl`}>
      {g.name.split(" ").map((w) => w[0]).join("").slice(0, 3)}
    </div>
  );
}

function Servers() {
  const { t } = useI18n();
  const session = useQuery(sessionQuery);
  // Refetch when coming back from the "Add to server" tab so the new server shows "Manage".
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["my-guilds"],
    queryFn: () => listMyGuilds(),
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  });
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("login") === "failed") {
      toast.error("Discord login failed. Please try again.");
      window.history.replaceState(null, "", "/dashboard");
    }
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-4 py-12">
      <h1 className="text-3xl font-bold">{t("yourServers")}</h1>
      <p className="mt-2 text-muted-foreground">{t("pickServer")}</p>
      {isLoading ? (
        <Loader2 className="mx-auto mt-16 h-8 w-8 animate-spin text-primary" />
      ) : !data?.signedIn ? (
        <div className="glass mt-10 rounded-2xl p-10 text-center">
          <p className="mb-4 text-muted-foreground">{t("signInFirst")}</p>
          <Button variant="discord" size="lg" onClick={openDiscordLogin} disabled={!session.data?.loginReady}>{t("login")}</Button>
          <Button variant="ghost" className="ms-2" onClick={() => refetch()}>↻</Button>
        </div>
      ) : (
        <>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.guilds.map((g) => (
              <div key={g.id} className="glass flex items-center gap-4 rounded-2xl p-4">
                <GuildAvatar g={g} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{g.name}</div>
                  {g.botIn ? (
                    <Button size="sm" className="mt-2" asChild>
                      <Link to="/dashboard/$guildId" params={{ guildId: g.id }}><Settings2 className="h-4 w-4" /> {t("manage")}</Link>
                    </Button>
                  ) : (
                    <Button size="sm" variant="outline" className="mt-2" asChild disabled={!g.inviteUrl}>
                      <a href={g.inviteUrl ?? "#"} target="_blank" rel="noreferrer"><Plus className="h-4 w-4" /> {t("invite")}</a>
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
          <Button variant="ghost" className="mt-6" onClick={() => refetch()} disabled={isFetching}>↻ Refresh</Button>
        </>
      )}
    </main>
  );
}
