"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, clearToken, getToken, post, useApi } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { NotificationItem, User } from "@/lib/types";
import AuthScreen, { NovaMark } from "./AuthScreen";
import { Icon } from "./icons";
import { Spinner, Toaster, toast } from "./ui";

const NAV: { group: string; items: { href: string; label: string; icon: string }[] }[] = [
  {
    group: "Operate",
    items: [
      { href: "/", label: "Dashboard", icon: "dashboard" },
      { href: "/chat", label: "AI Chat", icon: "chat" },
      { href: "/tasks", label: "Tasks", icon: "tasks" },
    ],
  },
  {
    group: "Create",
    items: [
      { href: "/studio", label: "Content Studio", icon: "studio" },
      { href: "/youtube", label: "YouTube Studio", icon: "youtube" },
      { href: "/instagram", label: "Instagram Studio", icon: "instagram" },
      { href: "/library", label: "Video Library", icon: "library" },
    ],
  },
  {
    group: "Knowledge",
    items: [
      { href: "/research", label: "Research", icon: "research" },
      { href: "/calendar", label: "Calendar", icon: "calendar" },
      { href: "/emails", label: "Emails", icon: "emails" },
      { href: "/files", label: "Files", icon: "files" },
      { href: "/memories", label: "Memories", icon: "memories" },
    ],
  },
  {
    group: "Control",
    items: [
      { href: "/integrations", label: "Integrations", icon: "integrations" },
      { href: "/settings", label: "Agent Settings", icon: "settings" },
      { href: "/permissions", label: "Permissions", icon: "permissions" },
      { href: "/logs", label: "Logs", icon: "logs" },
      { href: "/mobile", label: "Mobile", icon: "mobile" },
    ],
  },
];

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/chat": "AI Chat",
  "/tasks": "Tasks",
  "/studio": "Content Studio",
  "/youtube": "YouTube Studio",
  "/instagram": "Instagram Studio",
  "/library": "Video Library",
  "/research": "Research",
  "/calendar": "Calendar",
  "/emails": "Emails",
  "/files": "Files",
  "/memories": "Memories",
  "/integrations": "Integrations",
  "/settings": "Agent Settings",
  "/permissions": "Permissions",
  "/logs": "Logs",
  "/mobile": "Mobile",
};

const MOBILE_TABS = [
  { href: "/", label: "Home", icon: "dashboard" },
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/tasks", label: "Tasks", icon: "tasks" },
  { href: "/studio", label: "Create", icon: "studio" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    let active = true;
    const onUnauth = () => {
      if (active) setUser(null);
    };
    window.addEventListener("nova:unauth", onUnauth);
    if (!getToken()) {
      setReady(true);
    } else {
      api<User>("/api/auth/me")
        .then((value) => active && setUser(value))
        .catch(() => undefined)
        .finally(() => active && setReady(true));
    }
    return () => {
      active = false;
      window.removeEventListener("nova:unauth", onUnauth);
    };
  }, []);

  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
    const handler = (event: Event) => {
      event.preventDefault();
      (window as unknown as { __novaInstallPrompt?: Event }).__novaInstallPrompt = event;
      window.dispatchEvent(new Event("nova:installable"));
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  useEffect(() => {
    setDrawer(false);
    setNotificationsOpen(false);
  }, [pathname]);

  const bell = useApi<{ notifications: NotificationItem[] }>("/api/system/notifications", { pollMs: 30000 });
  const unread = (bell.data?.notifications ?? []).filter((item) => !item.read).length;

  const signOut = useCallback(() => {
    clearToken();
    setUser(null);
    router.push("/");
  }, [router]);

  const emergencyStop = useCallback(async () => {
    if (!window.confirm("Emergency stop: cancel every queued and running task?")) return;
    setStopping(true);
    try {
      const result = await post<{ task: { result?: { message?: string } } }>("/api/tasks", { prompt: "emergency stop" });
      toast(result.task.result?.message ?? "Emergency stop applied", "bad");
      router.refresh();
      router.push("/tasks");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Stop failed", "bad");
    } finally {
      setStopping(false);
    }
  }, [router]);

  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center text-mist-500">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (!user) {
    return (
      <>
        <AuthScreen onAuthenticated={setUser} />
        <Toaster />
      </>
    );
  }

  const title = TITLES[pathname] ?? (pathname.startsWith("/tasks/") ? "Task details" : "NOVA");

  return (
    <div className="min-h-screen lg:flex">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] flex-col border-r border-white/[0.06] bg-ink-950/70 backdrop-blur-xl lg:flex">
        <div className="flex items-center gap-3 px-5 py-5">
          <NovaMark size={34} />
          <div>
            <p className="text-[13px] font-semibold tracking-[0.2em] text-mist-100">NOVA</p>
            <p className="text-[10px] uppercase tracking-[0.16em] text-mist-500">Operator online</p>
          </div>
        </div>
        <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-6">
          {NAV.map((section) => (
            <div key={section.group}>
              <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-mist-600">
                {section.group}
              </p>
              <div className="space-y-0.5">
                {section.items.map((item) => {
                  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                  return (
                    <Link key={item.href} href={item.href} className={`nav-item ${active ? "nav-item-active" : ""}`}>
                      <Icon name={item.icon} className="h-4 w-4" />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-white/[0.06] p-3">
          <div className="flex items-center gap-2.5 rounded-xl px-2 py-2">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 text-[11px] font-semibold text-accent">
              {user.name?.slice(0, 2).toUpperCase() || "NO"}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-mist-200">{user.name || user.email}</p>
              <p className="truncate text-[10px] text-mist-500">{user.email}</p>
            </div>
            <button onClick={signOut} className="rounded-lg p-1.5 text-mist-500 hover:bg-white/5 hover:text-bad" aria-label="Sign out">
              <Icon name="logout" className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* mobile drawer */}
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 w-[280px] animate-fade-up overflow-y-auto border-r border-white/10 bg-ink-900 p-3">
            <div className="mb-4 flex items-center gap-3 px-2 py-2">
              <NovaMark size={30} />
              <span className="text-sm font-semibold tracking-[0.2em]">NOVA</span>
            </div>
            {NAV.map((section) => (
              <div key={section.group} className="mb-4">
                <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-mist-600">{section.group}</p>
                {section.items.map((item) => {
                  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                  return (
                    <Link key={item.href} href={item.href} className={`nav-item ${active ? "nav-item-active" : ""}`}>
                      <Icon name={item.icon} className="h-4 w-4" />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            ))}
            <button onClick={signOut} className="nav-item w-full text-bad">
              <Icon name="logout" className="h-4 w-4" /> Sign out
            </button>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:ml-[248px]">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-white/[0.06] bg-ink-900/80 px-4 backdrop-blur-xl sm:px-6">
          <button onClick={() => setDrawer(true)} className="rounded-lg p-1.5 text-mist-400 hover:bg-white/5 lg:hidden" aria-label="Menu">
            <Icon name="menu" className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-mist-100">{title}</h1>
            {user.phone ? (
              <p className="hidden text-[10px] text-mist-600 sm:block">WhatsApp: {user.phone}</p>
            ) : (
              <p className="hidden text-[10px] text-mist-600 sm:block">Add your phone in Mobile settings to control NOVA on WhatsApp</p>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="hidden items-center gap-1.5 rounded-full border border-good/20 bg-good/5 px-2.5 py-1 text-[10px] font-medium text-good sm:inline-flex">
              <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-good" /> Live
            </span>
            <div className="relative">
              <button
                onClick={() => setNotificationsOpen((open) => !open)}
                className="relative rounded-lg p-2 text-mist-400 hover:bg-white/5 hover:text-mist-100"
                aria-label="Notifications"
              >
                <Icon name="bell" className="h-[18px] w-[18px]" />
                {unread > 0 && (
                  <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-bad px-1 text-[9px] font-bold text-ink-950">
                    {unread > 9 ? "9+" : unread}
                  </span>
                )}
              </button>
              {notificationsOpen && (
                <div className="absolute right-0 top-11 w-[min(360px,calc(100vw-2rem))] animate-fade-up overflow-hidden rounded-xl border border-white/10 bg-ink-850 shadow-2xl">
                  <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5">
                    <span className="text-xs font-semibold">Notifications</span>
                    <button
                      className="text-[10px] text-mist-500 hover:text-mist-200"
                      onClick={async () => {
                        await post("/api/system/notifications/read-all");
                        bell.refresh();
                      }}
                    >
                      Mark all read
                    </button>
                  </div>
                  <div className="max-h-80 overflow-y-auto">
                    {(bell.data?.notifications ?? []).length === 0 && (
                      <p className="px-4 py-8 text-center text-xs text-mist-500">Nothing yet. Task updates land here.</p>
                    )}
                    {(bell.data?.notifications ?? []).slice(0, 20).map((item) => (
                      <div key={item.id} className={`border-b border-white/[0.04] px-4 py-3 ${item.read ? "opacity-60" : ""}`}>
                        <div className="flex items-center justify-between gap-2">
                          <p className="truncate text-[11px] font-medium text-mist-200">{item.title}</p>
                          <span className="shrink-0 text-[9px] text-mist-600">{relativeTime(item.created_at)}</span>
                        </div>
                        <p className="mt-0.5 line-clamp-2 whitespace-pre-line text-[11px] leading-relaxed text-mist-500">{item.body}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <button onClick={emergencyStop} disabled={stopping} className="btn-danger !px-2.5 !py-1.5 text-[11px]" title="Emergency stop">
              <Icon name="power" className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Stop</span>
            </button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 pb-24 pt-5 sm:px-6 sm:pb-10">{children}</main>

        <nav className="fixed bottom-0 left-0 right-0 z-30 flex border-t border-white/[0.07] bg-ink-950/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden">
          {MOBILE_TABS.map((tab) => {
            const active = tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] ${active ? "text-accent" : "text-mist-500"}`}
              >
                <Icon name={tab.icon} className="h-5 w-5" />
                {tab.label}
              </Link>
            );
          })}
          <button
            onClick={() => setDrawer(true)}
            className="flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] text-mist-500"
          >
            <Icon name="menu" className="h-5 w-5" />
            More
          </button>
        </nav>
      </div>
      <Toaster />
    </div>
  );
}
