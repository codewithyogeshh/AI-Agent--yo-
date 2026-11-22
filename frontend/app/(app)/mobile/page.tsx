"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, Panel, Toggle, toast } from "@/components/ui";
import { patch, post, put, useApi } from "@/lib/api";
import type { SettingsMap, User } from "@/lib/types";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export default function MobilePage() {
  const me = useApi<User>("/api/auth/me");
  const settings = useApi<{ settings: SettingsMap }>("/api/system/settings");
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);
  const [standalone, setStandalone] = useState(false);
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const stored = (window as unknown as { __novaInstallPrompt?: InstallPromptEvent }).__novaInstallPrompt;
    if (stored) setInstallEvent(stored);
    const handler = () => {
      const event = (window as unknown as { __novaInstallPrompt?: InstallPromptEvent }).__novaInstallPrompt;
      if (event) setInstallEvent(event);
    };
    window.addEventListener("nova:installable", handler);
    setStandalone(window.matchMedia("(display-mode: standalone)").matches);
    return () => window.removeEventListener("nova:installable", handler);
  }, []);

  useEffect(() => {
    if (me.data) setPhone(me.data.phone || "");
  }, [me.data]);

  async function install() {
    if (!installEvent) {
      toast("Use your browser menu → “Add to Home screen” to install NOVA.", "info");
      return;
    }
    await installEvent.prompt();
    const choice = await installEvent.userChoice;
    if (choice.outcome === "accepted") {
      setStandalone(true);
      toast("NOVA installed", "good");
    }
  }

  async function savePhone() {
    setSaving(true);
    try {
      await patch("/api/auth/me", { phone });
      toast("Phone number saved", "good");
      me.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not save", "bad");
    } finally {
      setSaving(false);
    }
  }

  async function requestNotifications() {
    if (!("Notification" in window)) {
      toast("This browser does not support notifications", "bad");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      new Notification("NOVA", { body: "Notifications are enabled on this device." });
      toast("Notifications enabled", "good");
    } else {
      toast("Notification permission denied", "bad");
    }
  }

  async function emergencyStop() {
    if (!window.confirm("Cancel every active task right now?")) return;
    try {
      const result = await post<{ task: { result?: { message?: string } } }>("/api/tasks", { prompt: "emergency stop" });
      toast(result.task.result?.message ?? "All tasks cancelled", "bad");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Stop failed", "bad");
    }
  }

  async function toggleVoice(value: boolean) {
    try {
      await put("/api/system/settings", { voice_enabled: value });
      settings.refresh();
      toast(`Voice replies ${value ? "enabled" : "disabled"}`, "good");
    } catch {
      toast("Could not update", "bad");
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Mobile &amp; devices</h2>
        <p className="text-xs text-mist-500">Install NOVA as an app, wire up WhatsApp and control access from your phone.</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Install the app" subtitle="Progressive Web App · Android, iOS, desktop">
          <div className="space-y-3 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/icons/icon-192.png" alt="NOVA" className="h-10 w-10 rounded-xl" />
                <div>
                  <p className="text-[13px] font-medium text-mist-100">NOVA</p>
                  <p className="text-[10px] text-mist-500">Standalone window · offline shell</p>
                </div>
              </div>
              <Badge status={standalone ? "connected" : "draft"} label={standalone ? "installed" : "installable"} />
            </div>
            <button onClick={install} className="btn-primary w-full">
              <Icon name="download" className="h-4 w-4" /> {standalone ? "Open installed app" : "Install NOVA"}
            </button>
            <p className="text-[10px] leading-relaxed text-mist-600">
              Chrome/Edge: menu → Add to Home screen. iOS Safari: Share → Add to Home Screen. PWA install requires HTTPS in
              production (localhost is exempt).
            </p>
          </div>
        </Panel>

        <Panel title="Notifications" subtitle="Task completion and approvals">
          <div className="space-y-3 px-5 py-4">
            <Toggle
              checked={Boolean(settings.data?.settings.voice_enabled)}
              onChange={toggleVoice}
              label="Voice replies in chat"
              description="Uses the on-device speech engine; no audio leaves your phone."
            />
            <button onClick={requestNotifications} className="btn-ghost w-full !py-2 text-[12px]">
              <Icon name="bell" className="h-4 w-4" /> Enable browser notifications
            </button>
            <p className="text-[10px] leading-relaxed text-mist-600">
              Real-time updates use SSE while the app is open. Background push requires a VAPID key pair and is not configured
              yet — WhatsApp messages cover that gap today.
            </p>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="WhatsApp control" subtitle="Number linked to your NOVA account">
          <div className="space-y-3 px-5 py-4">
            <div>
              <label className="label">Your WhatsApp number (E.164)</label>
              <input className="input" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+919876543210" />
              <p className="mt-1 text-[10px] leading-relaxed text-mist-600">
                This number must also appear in <span className="code">WHATSAPP_ALLOWED_NUMBERS</span> on the backend, otherwise
                inbound instructions are rejected.
              </p>
            </div>
            <button onClick={savePhone} disabled={saving} className="btn-primary w-full !py-2 text-[12px]">
              {saving ? "Saving…" : "Save number"}
            </button>
            <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[10px] leading-relaxed text-mist-500">
              Once connected you can text or send voice notes: “find the latest AI news”, “make a 60-second reel about Java”,
              “pause all tasks”, “cancel task 14”.
            </p>
          </div>
        </Panel>

        <Panel title="Emergency stop" subtitle="Immediate, server-side">
          <div className="space-y-3 px-5 py-4">
            <p className="text-[11px] leading-relaxed text-mist-500">
              Cancels every queued, planning and running task for your account. Approvals are dropped with their tasks.
            </p>
            <button onClick={emergencyStop} className="btn-danger w-full">
              <Icon name="power" className="h-4 w-4" /> Stop everything now
            </button>
            <p className="text-[10px] leading-relaxed text-mist-600">
              A running tool call finishes its current step, then stops. Nothing new is scheduled.
            </p>
          </div>
        </Panel>
      </div>

      <Panel title="Device access" subtitle="Current session">
        <div className="space-y-2 px-5 py-4 text-[11px] text-mist-400">
          <div className="flex items-center justify-between gap-3">
            <span>Account</span>
            <span className="text-mist-200">{me.data?.email ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Role</span>
            <span className="chip border-white/10 text-[10px]">{me.data?.role ?? "owner"}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Mode</span>
            <span className="text-mist-200">{standalone ? "installed app" : "browser tab"}</span>
          </div>
          <p className="pt-2 text-[10px] leading-relaxed text-mist-600">
            Sessions expire after 12 hours. Sign out from the sidebar to clear the token from this device.
          </p>
        </div>
      </Panel>
    </div>
  );
}
