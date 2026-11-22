"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Panel, Skeleton, Toggle, toast } from "@/components/ui";
import { api, post, put, useApi } from "@/lib/api";
import type { AiCapabilities, MediaCapabilities, SettingsMap, ToolSpec, WorkerStatus } from "@/lib/types";

interface Capabilities {
  ai: AiCapabilities;
  media: MediaCapabilities;
  worker: WorkerStatus;
}

export default function SettingsPage() {
  const capabilities = useApi<Capabilities>("/api/system/capabilities", { pollMs: 30000 });
  const settings = useApi<{ settings: SettingsMap }>("/api/system/settings");
  const tools = useApi<{ tools: ToolSpec[] }>("/api/system/tools");
  const [local, setLocal] = useState<SettingsMap | null>(null);
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState({ current_password: "", new_password: "" });

  useEffect(() => {
    if (settings.data) setLocal(settings.data.settings);
  }, [settings.data]);

  async function save(patch: Partial<SettingsMap>) {
    if (!local) return;
    const next = { ...local, ...patch };
    setLocal(next);
    setSaving(true);
    try {
      await put("/api/system/settings", patch);
      toast("Settings saved", "good");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Save failed", "bad");
    } finally {
      setSaving(false);
    }
  }

  async function changePassword() {
    try {
      await post("/api/auth/change-password", password);
      toast("Password updated", "good");
      setPassword({ current_password: "", new_password: "" });
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not change password", "bad");
    }
  }

  const ai = capabilities.data?.ai;
  const media = capabilities.data?.media;
  const worker = capabilities.data?.worker;
  const grouped = (tools.data?.tools ?? []).reduce<Record<string, ToolSpec[]>>((acc, tool) => {
    acc[tool.category] = [...(acc[tool.category] ?? []), tool];
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Agent settings</h2>
        <p className="text-xs text-mist-500">Runtime capability, defaults and account security. Everything here is live — no mock switches.</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Runtime" subtitle="What the agent can actually do right now">
          {capabilities.loading && !capabilities.data ? (
            <div className="space-y-2 p-4"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
          ) : (
            <div className="divide-y divide-white/[0.05]">
              <Row label="AI provider" value={ai?.configured ? `${ai.provider} · ${ai.model}` : "offline deterministic planner"} ok={Boolean(ai?.configured)} />
              <Row label="Task worker" value={worker ? `${worker.alive ? "running" : "stopped"} · ${worker.running}/${worker.concurrency} slots` : "—"} ok={Boolean(worker?.alive)} />
              <Row label="Video renderer" value={media?.ffmpeg ? "ffmpeg available" : "ffmpeg missing"} ok={Boolean(media?.ffmpeg)} />
              <Row label="Voiceover" value={media?.tts ? "TTS configured" : "silent audio only"} ok={Boolean(media?.tts)} />
              <Row label="Web research" value="DuckDuckGo live fetch" ok />
            </div>
          )}
          {ai?.offline_mode && (
            <p className="border-t border-white/[0.05] px-5 py-3 text-[10px] leading-relaxed text-mist-500">
              Add <span className="code">GEMINI_API_KEY</span>, <span className="code">OPENAI_API_KEY</span> or{" "}
              <span className="code">ANTHROPIC_API_KEY</span> to <span className="code">backend/.env</span> and restart to enable
              generative planning and writing. Everything else already works.
            </p>
          )}
        </Panel>

        <Panel title="Defaults" subtitle="Applied to new tasks and productions">
          {!local ? (
            <div className="space-y-2 p-4"><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /></div>
          ) : (
            <div className="space-y-3 px-5 py-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">Video format</label>
                  <select className="input" value={local.default_video_format} onChange={(event) => save({ default_video_format: event.target.value })}>
                    <option value="vertical">Vertical 9:16</option>
                    <option value="landscape">Landscape 16:9</option>
                    <option value="square">Square 1:1</option>
                  </select>
                </div>
                <div>
                  <label className="label">Language</label>
                  <select className="input" value={local.default_language} onChange={(event) => save({ default_language: event.target.value })}>
                    <option value="en">English</option>
                    <option value="hi">Hindi</option>
                    <option value="es">Spanish</option>
                    <option value="fr">French</option>
                  </select>
                </div>
                <div>
                  <label className="label">Research depth</label>
                  <select className="input" value={local.research_depth} onChange={(event) => save({ research_depth: event.target.value })}>
                    <option value="quick">Quick (2 sources)</option>
                    <option value="standard">Standard (4 sources)</option>
                    <option value="deep">Deep (8 sources)</option>
                  </select>
                </div>
                <div>
                  <label className="label">Daily AI budget (USD)</label>
                  <input
                    type="number"
                    min={0}
                    step={0.25}
                    className="input"
                    value={local.daily_ai_budget_usd}
                    onChange={(event) => setLocal({ ...local, daily_ai_budget_usd: Number(event.target.value) })}
                    onBlur={(event) => save({ daily_ai_budget_usd: Number(event.target.value) })}
                  />
                </div>
              </div>
              <div className="border-t border-white/[0.05] pt-2">
                <Toggle
                  checked={local.notify_on_complete}
                  onChange={(value) => save({ notify_on_complete: value })}
                  label="Notify when a task finishes"
                  description="Dashboard notification always; WhatsApp too when configured and your number is linked."
                />
                <Toggle
                  checked={local.voice_enabled}
                  onChange={(value) => save({ voice_enabled: value })}
                  label="Voice replies in chat"
                  description="Reads assistant replies aloud using the browser speech engine."
                />
              </div>
              {saving && <p className="text-[10px] text-mist-600">Saving…</p>}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Tool registry" subtitle={`${tools.data?.tools.length ?? 0} tools available to the planner`}>
        {tools.loading && !tools.data ? (
          <div className="space-y-2 p-4"><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /></div>
        ) : (
          <div className="divide-y divide-white/[0.04]">
            {Object.entries(grouped).map(([category, items]) => (
              <div key={category} className="px-5 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-mist-600">{category}</p>
                <div className="mt-2 space-y-1.5">
                  {items.map((tool) => (
                    <div key={tool.name} className="flex flex-wrap items-center gap-2">
                      <span className="code">{tool.name}</span>
                      <span className={`chip text-[9px] ${tool.risk === "blocked" ? "border-bad/25 bg-bad/5 text-bad" : tool.risk === "confirm" ? "border-warn/25 bg-warn/5 text-warn" : "border-white/10 text-mist-500"}`}>
                        {tool.risk}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[10px] text-mist-500">{tool.description}</span>
                      {tool.requires.length > 0 && <span className="text-[9px] text-mist-600">needs {tool.requires.join(", ")}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {Object.keys(grouped).length === 0 && <EmptyState title="No tools registered" />}
          </div>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Session security" subtitle="Password and active session">
          <div className="space-y-3 px-5 py-4">
            <div>
              <label className="label">Current password</label>
              <input type="password" className="input" value={password.current_password} onChange={(event) => setPassword({ ...password, current_password: event.target.value })} />
            </div>
            <div>
              <label className="label">New password (min 10 chars)</label>
              <input type="password" className="input" value={password.new_password} onChange={(event) => setPassword({ ...password, new_password: event.target.value })} />
            </div>
            <button onClick={changePassword} disabled={!password.current_password || password.new_password.length < 10} className="btn-primary w-full">
              Update password
            </button>
            <p className="text-[10px] leading-relaxed text-mist-600">
              Sessions are signed JWTs valid for 12 hours. Change NOVA_SECRET_KEY to invalidate all sessions.
            </p>
          </div>
        </Panel>

        <Panel title="API access" subtitle="For the desktop bridge and mobile clients">
          <div className="space-y-3 px-5 py-4 text-[11px] leading-relaxed text-mist-500">
            <div className="flex items-center justify-between gap-2">
              <span>REST base</span>
              <code className="code">/api</code>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>Live events</span>
              <code className="code">/api/system/events (SSE)</code>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>WebSocket</span>
              <code className="code">/ws?token=…</code>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>OpenAPI docs</span>
              <a href="/api/proxy/docs" target="_blank" rel="noopener noreferrer" className="text-accent-soft hover:underline">backend /docs ↗</a>
            </div>
            <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2">
              The desktop bridge authenticates with <span className="code">DESKTOP_BRIDGE_TOKEN</span> and can only run commands
              from <span className="code">DESKTOP_ALLOWED_COMMANDS</span>.
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Row({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-3">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-good" : "bg-warn"}`} />
        <span className="text-[12px] text-mist-300">{label}</span>
      </div>
      <span className="max-w-[60%] truncate text-right text-[10px] text-mist-500">{value}</span>
    </div>
  );
}
