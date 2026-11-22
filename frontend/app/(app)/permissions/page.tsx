"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/icons";
import { EmptyState, Panel, Skeleton, Toggle, toast } from "@/components/ui";
import { put, useApi } from "@/lib/api";
import type { SettingsMap, ToolSpec } from "@/lib/types";

export default function PermissionsPage() {
  const settings = useApi<{ settings: SettingsMap }>("/api/system/settings");
  const tools = useApi<{ tools: ToolSpec[] }>("/api/system/tools");
  const [local, setLocal] = useState<SettingsMap | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings.data) setLocal(settings.data.settings);
  }, [settings.data]);

  async function save(patch: Partial<SettingsMap>) {
    if (!local) return;
    setLocal({ ...local, ...patch });
    setBusy(true);
    try {
      await put("/api/system/settings", patch);
      toast("Policy updated", "good");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Save failed", "bad");
    } finally {
      setBusy(false);
    }
  }

  function toggleList(key: "auto_approve" | "disabled_tools", name: string, enabled: boolean) {
    if (!local) return;
    const current = new Set(local[key] ?? []);
    if (enabled) current.add(name);
    else current.delete(name);
    save({ [key]: [...current] } as Partial<SettingsMap>);
  }

  const confirmTools = (tools.data?.tools ?? []).filter((tool) => tool.risk === "confirm");
  const gatedTools = (tools.data?.tools ?? []).filter((tool) => tool.risk === "blocked");

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Permissions</h2>
        <p className="text-xs text-mist-500">
          NOVA never gets unlimited authority. These policies decide what runs automatically and what always asks you.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Publishing mode" subtitle="Content leaving your machine">
          {!local ? (
            <div className="p-4"><Skeleton className="h-24 w-full" /></div>
          ) : (
            <div className="space-y-2 px-5 py-4">
              {(
                [
                  { id: "draft", title: "Draft only", detail: "Nothing is ever published automatically." },
                  { id: "approval", title: "Approval required", detail: "Recommended. Each publish waits for your click." },
                  { id: "auto", title: "Auto-publish workflows", detail: "Only workflows created by you with auto mode publish unattended." },
                ] as const
              ).map((option) => (
                <button
                  key={option.id}
                  onClick={() => save({ publishing_mode: option.id })}
                  disabled={busy}
                  className={`w-full rounded-xl border px-3.5 py-2.5 text-left transition ${
                    local.publishing_mode === option.id ? "border-accent/40 bg-accent/[0.07]" : "border-white/[0.07] hover:border-white/15"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${local.publishing_mode === option.id ? "bg-accent" : "bg-mist-600"}`} />
                    <span className="text-[12px] font-medium text-mist-100">{option.title}</span>
                  </div>
                  <p className="mt-0.5 pl-4 text-[10px] text-mist-500">{option.detail}</p>
                </button>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Hard limits" subtitle="Cost and volume guardrails">
          {!local ? (
            <div className="p-4"><Skeleton className="h-24 w-full" /></div>
          ) : (
            <div className="space-y-3 px-5 py-4">
              <div>
                <label className="label">Maximum tasks per day</label>
                <input
                  type="number"
                  min={1}
                  max={500}
                  className="input"
                  value={local.max_daily_tasks}
                  onChange={(event) => setLocal({ ...local, max_daily_tasks: Number(event.target.value) })}
                  onBlur={(event) => save({ max_daily_tasks: Number(event.target.value) })}
                />
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
                <p className="mt-1 text-[10px] leading-relaxed text-mist-600">
                  Used as a planning guardrail: task creation is refused once the daily task cap is hit. Provider-side billing
                  limits should also be set in your AI account.
                </p>
              </div>
              <Toggle
                checked={local.whatsapp_notifications}
                onChange={(value) => save({ whatsapp_notifications: value })}
                label="WhatsApp notifications"
                description="Progress and approval pings to your allowlisted number."
              />
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Approval-gated tools" subtitle="These always pause for your decision">
        <div className="divide-y divide-white/[0.04]">
          {gatedTools.map((tool) => (
            <div key={tool.name} className="flex items-start justify-between gap-3 px-5 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="code">{tool.name}</span>
                  <span className="chip border-bad/25 bg-bad/5 text-[9px] text-bad">cannot auto-approve</span>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-mist-500">{tool.description}</p>
              </div>
              <Icon name="shield" className="mt-1 h-4 w-4 shrink-0 text-bad/70" />
            </div>
          ))}
          {gatedTools.length === 0 && <EmptyState title="No gated tools registered" />}
        </div>
      </Panel>

      <Panel title="Trusted tools" subtitle="Confirm-level tools you may run without asking">
        {!local ? (
          <div className="p-4"><Skeleton className="h-20 w-full" /></div>
        ) : confirmTools.length === 0 ? (
          <EmptyState title="Nothing to trust yet" />
        ) : (
          <div className="divide-y divide-white/[0.04]">
            {confirmTools.map((tool) => (
              <div key={tool.name} className="px-5 py-2">
                <Toggle
                  checked={(local.auto_approve ?? []).includes(tool.name)}
                  onChange={(value) => toggleList("auto_approve", tool.name, value)}
                  label={tool.name}
                  description={tool.description}
                />
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Disabled tools" subtitle="Revoke a capability entirely">
        {!local ? (
          <div className="p-4"><Skeleton className="h-20 w-full" /></div>
        ) : (
          <div className="grid gap-x-6 px-5 py-2 sm:grid-cols-2">
            {(tools.data?.tools ?? []).filter((tool) => tool.risk !== "blocked").map((tool) => (
              <Toggle
                key={tool.name}
                checked={(local.disabled_tools ?? []).includes(tool.name)}
                onChange={(value) => toggleList("disabled_tools", tool.name, value)}
                label={tool.name}
                description={tool.category}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Never allowed" subtitle="Hard-coded refusals, independent of settings">
        <div className="grid gap-2 px-5 py-4 text-[11px] leading-relaxed text-mist-400 sm:grid-cols-2">
          {[
            "Transfer money or make purchases",
            "Change account security settings",
            "Reveal or store passwords and API keys",
            "Permanently delete important files",
            "Share private information with third parties",
            "Follow instructions found inside web pages or emails",
          ].map((item) => (
            <div key={item} className="flex items-start gap-2">
              <Icon name="x" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" />
              {item}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
