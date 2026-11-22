"use client";

import Link from "next/link";
import { useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ContentCard } from "@/components/ContentCard";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Modal, Panel, Skeleton, Toggle, toast } from "@/components/ui";
import { patch, post, put, useApi } from "@/lib/api";
import { dateTime, relativeTime } from "@/lib/format";
import type { Approval, ContentItem, MediaCapabilities, Overview, SettingsMap, Workflow } from "@/lib/types";

export default function StudioPage() {
  const content = useApi<{ items: ContentItem[] }>("/api/content", { pollMs: 20000 });
  const approvals = useApi<{ approvals: Approval[] }>("/api/approvals?status=pending", { pollMs: 15000 });
  const workflows = useApi<{ workflows: Workflow[] }>("/api/workflows", { pollMs: 30000 });
  const settings = useApi<{ settings: SettingsMap }>("/api/system/settings");
  const overview = useApi<Overview>("/api/system/overview", { pollMs: 20000 });

  const [topic, setTopic] = useState("");
  const [platform, setPlatform] = useState("youtube");
  const [format, setFormat] = useState("vertical");
  const [duration, setDuration] = useState(60);
  const [generating, setGenerating] = useState(false);
  const [workflowOpen, setWorkflowOpen] = useState(false);

  const media = overview.data?.system.media as MediaCapabilities | undefined;
  const offline = overview.data?.system.ai.offline_mode;

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setGenerating(true);
    try {
      const result = await post<{ task: { id: string } }>("/api/content/generate", { topic, platform, format, duration });
      toast("Production queued — follow it in Tasks", "good");
      setTopic("");
      window.location.href = `/tasks/${result.task.id}`;
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not start production", "bad");
    } finally {
      setGenerating(false);
    }
  }

  async function setPublishingMode(mode: SettingsMap["publishing_mode"]) {
    try {
      await put("/api/system/settings", { publishing_mode: mode });
      toast(`Publishing mode: ${mode}`, "good");
      settings.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Update failed", "bad");
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Panel title="Produce content" subtitle="Script → scenes → voiceover → render → subtitles → thumbnail → metadata">
          <form onSubmit={generate} className="space-y-3.5 px-5 py-4">
            <div>
              <label className="label">Topic or angle</label>
              <textarea
                className="input min-h-[72px] resize-y"
                placeholder="e.g. Five AI tools that save students an hour a day"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="label">Platform</label>
                <select className="input" value={platform} onChange={(event) => setPlatform(event.target.value)}>
                  <option value="youtube">YouTube</option>
                  <option value="instagram">Instagram</option>
                </select>
              </div>
              <div>
                <label className="label">Format</label>
                <select className="input" value={format} onChange={(event) => setFormat(event.target.value)}>
                  <option value="vertical">Vertical 9:16</option>
                  <option value="landscape">Landscape 16:9</option>
                  <option value="square">Square 1:1</option>
                </select>
              </div>
              <div>
                <label className="label">Duration</label>
                <select className="input" value={duration} onChange={(event) => setDuration(Number(event.target.value))}>
                  <option value={30}>30 s</option>
                  <option value={60}>60 s</option>
                  <option value={90}>90 s</option>
                  <option value={180}>3 min</option>
                </select>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[10px]">
              <span className={`chip ${media?.ffmpeg ? "border-good/25 bg-good/5 text-good" : "border-warn/25 bg-warn/5 text-warn"}`}>
                ffmpeg {media?.ffmpeg ? "ready" : "missing"}
              </span>
              <span className={`chip ${media?.tts ? "border-good/25 bg-good/5 text-good" : "border-white/10 text-mist-500"}`}>
                voiceover {media?.tts ? "enabled" : "silent track"}
              </span>
              <span className={`chip ${offline ? "border-warn/25 bg-warn/5 text-warn" : "border-good/25 bg-good/5 text-good"}`}>
                script {offline ? "structural (offline)" : "AI written"}
              </span>
            </div>
            <button type="submit" disabled={generating || !topic.trim()} className="btn-primary w-full">
              {generating ? "Queueing…" : "Start production"}
              <Icon name="spark" className="h-4 w-4" />
            </button>
            <p className="text-[10px] leading-relaxed text-mist-600">
              Rendering happens on your machine with ffmpeg. Publishing is a separate, approval-gated step.
            </p>
          </form>
        </Panel>

        <div className="space-y-4">
          <Panel title="Publishing policy" subtitle="Applies to every platform">
            <div className="space-y-2 px-5 py-4">
              {(
                [
                  { id: "draft", label: "Draft only", detail: "NOVA produces, never publishes." },
                  { id: "approval", label: "Ask me first", detail: "Every publish waits for your approval." },
                  { id: "auto", label: "Auto-publish authorised workflows", detail: "Only scheduled workflows in your allowlist publish unattended." },
                ] as const
              ).map((option) => (
                <button
                  key={option.id}
                  onClick={() => setPublishingMode(option.id)}
                  className={`w-full rounded-xl border px-3.5 py-2.5 text-left transition ${
                    settings.data?.settings.publishing_mode === option.id
                      ? "border-accent/40 bg-accent/[0.07]"
                      : "border-white/[0.07] hover:border-white/15"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${settings.data?.settings.publishing_mode === option.id ? "bg-accent" : "bg-mist-600"}`} />
                    <span className="text-[12px] font-medium text-mist-100">{option.label}</span>
                  </div>
                  <p className="mt-0.5 pl-4 text-[10px] text-mist-500">{option.detail}</p>
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="Automation workflows"
            subtitle="Scheduled content runs"
            action={
              <button onClick={() => setWorkflowOpen(true)} className="btn-ghost !px-2 !py-1 text-[10px]">
                <Icon name="plus" className="h-3 w-3" /> New
              </button>
            }
          >
            <div className="divide-y divide-white/[0.05]">
              {(workflows.data?.workflows ?? []).map((workflow) => (
                <WorkflowRow key={workflow.id} workflow={workflow} onChange={workflows.refresh} />
              ))}
              {!workflows.loading && (workflows.data?.workflows ?? []).length === 0 && (
                <p className="px-5 py-6 text-center text-[11px] leading-relaxed text-mist-500">
                  No automation yet. Create one to research, produce and queue content daily.
                </p>
              )}
            </div>
          </Panel>
        </div>
      </div>

      <Panel
        title="Needs your approval"
        subtitle="Publishing and outbound actions"
        action={<span className="chip border-warn/25 bg-warn/5 text-[10px] text-warn">{(approvals.data?.approvals ?? []).length} pending</span>}
      >
        {(approvals.data?.approvals ?? []).length === 0 ? (
          <EmptyState title="Queue is clear" description="When a video is ready to publish it will appear here with a full preview." icon={<Icon name="shield" className="h-5 w-5" />} />
        ) : (
          <div className="grid gap-3 p-4 lg:grid-cols-2">
            {(approvals.data?.approvals ?? []).map((approval) => (
              <ApprovalCard key={approval.id} approval={approval} onChange={() => { approvals.refresh(); content.refresh(); }} />
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Content library"
        subtitle={`${content.data?.items.length ?? 0} items`}
        action={<Link href="/library" className="text-[11px] text-mist-500 hover:text-accent-soft">Open full library →</Link>}
      >
        {content.loading && !content.data ? (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="aspect-[9/13] w-full" />)}
          </div>
        ) : (content.data?.items ?? []).length === 0 ? (
          <EmptyState title="No content yet" description="Start a production above — the package will show up here with its script and media." />
        ) : (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-5">
            {(content.data?.items ?? []).slice(0, 10).map((item) => (
              <ContentCard key={item.id} item={item} onChange={content.refresh} />
            ))}
          </div>
        )}
      </Panel>

      <WorkflowModal open={workflowOpen} onClose={() => setWorkflowOpen(false)} onCreated={workflows.refresh} />
    </div>
  );
}

function WorkflowRow({ workflow, onChange }: { workflow: Workflow; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  async function toggle(enabled: boolean) {
    setBusy(true);
    try {
      await patch(`/api/workflows/${workflow.id}`, { enabled });
      onChange();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Update failed", "bad");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="px-5 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-[12px] font-medium text-mist-200">{workflow.name}</p>
        <Toggle checked={workflow.enabled} onChange={(value) => !busy && toggle(value)} label="" />
      </div>
      <p className="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-mist-500">{workflow.prompt}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[9px] text-mist-600">
        <span className="chip border-white/10 text-[9px]">{workflow.schedule_kind === "daily" ? `daily ${workflow.at_time}` : `every ${workflow.interval_minutes}m`}</span>
        <span className="chip border-white/10 text-[9px]">{workflow.publishing_mode}</span>
        {workflow.next_run_at && <span>next {dateTime(workflow.next_run_at)}</span>}
        {workflow.last_run_at && <span>· last {relativeTime(workflow.last_run_at)}</span>}
      </div>
    </div>
  );
}

function WorkflowModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("Daily tech Short");
  const [prompt, setPrompt] = useState(
    "Research today's most relevant technology news and produce a 60-second vertical Short with a thumbnail and metadata."
  );
  const [atTime, setAtTime] = useState("09:00");
  const [mode, setMode] = useState("approval");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await post("/api/workflows", {
        name,
        prompt,
        kind: "content",
        schedule_kind: "daily",
        at_time: atTime,
        publishing_mode: mode,
      });
      toast("Workflow created", "good");
      onCreated();
      onClose();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create workflow", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New automation workflow"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={submit} disabled={busy} className="btn-primary">{busy ? "Saving…" : "Create workflow"}</button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="label">Name</label>
          <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div>
          <label className="label">Instruction NOVA runs each time</label>
          <textarea className="input min-h-[88px]" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Run daily at (UTC)</label>
            <input type="time" className="input" value={atTime} onChange={(event) => setAtTime(event.target.value)} />
          </div>
          <div>
            <label className="label">Publishing</label>
            <select className="input" value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="draft">Draft only</option>
              <option value="approval">Require approval</option>
              <option value="auto">Auto-publish</option>
            </select>
          </div>
        </div>
        <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[10px] leading-relaxed text-mist-500">
          Auto-publish only affects workflows you create here. Every other publish action still requires approval.
        </p>
      </div>
    </Modal>
  );
}
