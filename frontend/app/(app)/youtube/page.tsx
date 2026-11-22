"use client";

import Link from "next/link";
import { useState } from "react";
import { ContentCard } from "@/components/ContentCard";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Panel, Skeleton, Stat, toast } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { dateTime, relativeTime } from "@/lib/format";
import type { ContentItem, IntegrationPayload, Overview, Workflow } from "@/lib/types";

interface AnalyticsResponse {
  ok: boolean;
  configured: boolean;
  detail: string;
  data: Record<string, string | number>;
  setup_required: string;
}

export default function YouTubePage() {
  const integrations = useApi<IntegrationPayload>("/api/integrations", { pollMs: 60000 });
  const analytics = useApi<AnalyticsResponse>("/api/publishing/youtube/analytics", { pollMs: 60000 });
  const content = useApi<{ items: ContentItem[] }>("/api/content?platform=youtube", { pollMs: 20000 });
  const workflows = useApi<{ workflows: Workflow[] }>("/api/workflows");
  const overview = useApi<Overview>("/api/system/overview");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);

  const youtube = integrations.data?.integrations.find((item) => item.id === "youtube");
  const rendered = (content.data?.items ?? []).filter((item) => item.has_video && item.status !== "published");
  const published = (content.data?.items ?? []).filter((item) => item.status === "published");

  async function produce(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setBusy(true);
    try {
      const result = await post<{ task: { id: string } }>("/api/content/generate", {
        topic,
        platform: "youtube",
        format: "vertical",
        duration: 60,
      });
      toast("Production queued", "good");
      window.location.href = `/tasks/${result.task.id}`;
    } catch (error) {
      toast(error instanceof Error ? error.message : "Failed", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">YouTube Studio</h2>
          <p className="text-xs text-mist-500">Official YouTube Data API · uploads always gated by approval.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`chip ${youtube?.status === "connected" ? "border-good/25 bg-good/5 text-good" : "border-warn/25 bg-warn/5 text-warn"}`}>
            {youtube?.status === "connected" ? "channel connected" : youtube?.status === "needs_auth" ? "authorise channel" : "credentials missing"}
          </span>
          <Link href="/integrations" className="btn-ghost !py-1.5 text-[11px]">
            <Icon name="integrations" className="h-3.5 w-3.5" /> Manage
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Subscribers" value={analytics.data?.data?.subscribers ?? "—"} hint={analytics.data?.ok ? "from YouTube" : "not connected"} tone="accent" />
        <Stat label="Total views" value={analytics.data?.data?.views ?? "—"} hint="channel lifetime" />
        <Stat label="Videos" value={analytics.data?.data?.videos ?? "—"} hint="on the channel" />
        <Stat label="Ready to publish" value={rendered.length} hint={`${published.length} published`} tone={rendered.length ? "warn" : "default"} />
      </div>

      {analytics.data && !analytics.data.ok && (
        <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/[0.02] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2.5">
            <Icon name="youtube" className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
            <p className="text-xs leading-relaxed text-mist-400">
              {analytics.data?.detail || "Connect a YouTube channel to read real analytics and upload."}
            </p>
          </div>
          <Link href="/integrations" className="btn-ghost shrink-0 !py-1.5 text-[11px]">Connection setup</Link>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Panel title="Start a video" subtitle="Script, render, thumbnail and metadata in one task">
          <form onSubmit={produce} className="space-y-3 px-5 py-4">
            <div>
              <label className="label">Video idea</label>
              <textarea
                className="input min-h-[80px] resize-y"
                placeholder="e.g. Why async Python is faster than you think — with one benchmark"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
            </div>
            <div className="flex flex-wrap gap-2 text-[10px] text-mist-500">
              <span className="chip border-white/10">vertical short</span>
              <span className="chip border-white/10">60 s</span>
              <span className="chip border-white/10">burned-in subtitles</span>
              <span className="chip border-white/10">AI thumbnail</span>
            </div>
            <button type="submit" disabled={busy || !topic.trim()} className="btn-primary w-full">
              {busy ? "Queueing…" : "Produce video"}
            </button>
          </form>
        </Panel>

        <Panel title="Channel pipeline" subtitle="What happens after production">
          <ol className="space-y-3 px-5 py-4 text-[11px] leading-relaxed text-mist-400">
            {[
              "Research and draft the script (AI provider required for written prose)",
              "Render the MP4 with ffmpeg, burn subtitles and generate a thumbnail",
              "Save the draft with title, description, tags and hashtags",
              "Approve the upload — NOVA never publishes on its own by default",
              "Upload with the official resumable API, then attach the thumbnail",
              "Track performance through the YouTube Analytics API",
            ].map((step, index) => (
              <li key={step} className="flex gap-2.5">
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-white/10 text-[9px] text-mist-500">{index + 1}</span>
                {step}
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <Panel title="Ready to upload" subtitle="Rendered videos awaiting an upload decision">
        {content.loading && !content.data ? (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="aspect-[9/13] w-full" />)}
          </div>
        ) : rendered.length === 0 ? (
          <EmptyState title="Nothing waiting" description="Produce a video above and it will appear here with a preview and publish button." />
        ) : (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-4">
            {rendered.map((item) => <ContentCard key={item.id} item={item} onChange={content.refresh} />)}
          </div>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Published" subtitle="Uploaded from NOVA">
          {published.length === 0 ? (
            <EmptyState title="No uploads yet" description="Published videos will be listed here with their YouTube IDs." />
          ) : (
            <ul className="divide-y divide-white/[0.05]">
              {published.map((item) => (
                <li key={item.id} className="flex items-center gap-3 px-5 py-3">
                  <Icon name="youtube" className="h-4 w-4 shrink-0 text-bad" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] text-mist-200">{item.title}</p>
                    <p className="text-[10px] text-mist-600">
                      {item.published_at ? `published ${relativeTime(item.published_at)}` : "published"} · {item.external_id || "pending id"}
                    </p>
                  </div>
                  {item.external_id && (
                    <a href={`https://youtu.be/${item.external_id}`} target="_blank" rel="noopener noreferrer" className="btn-ghost !px-2 !py-1 text-[10px]">
                      <Icon name="external" className="h-3 w-3" /> Open
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Scheduled workflows" subtitle="Daily content automation">
          {(workflows.data?.workflows ?? []).length === 0 ? (
            <EmptyState
              title="No workflows"
              description="Automate a daily research → produce → draft cycle."
              action={<Link href="/studio" className="btn-ghost !py-1.5 text-[11px]">Create in studio</Link>}
            />
          ) : (
            <ul className="divide-y divide-white/[0.05]">
              {(workflows.data?.workflows ?? []).map((workflow) => (
                <li key={workflow.id} className="px-5 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-[12px] text-mist-200">{workflow.name}</p>
                    <Badge status={workflow.enabled ? "success" : "paused"} label={workflow.enabled ? "enabled" : "paused"} />
                  </div>
                  <p className="mt-0.5 text-[10px] text-mist-600">
                    {workflow.schedule_kind === "daily" ? `daily at ${workflow.at_time} UTC` : `every ${workflow.interval_minutes} min`}
                    {workflow.next_run_at ? ` · next ${dateTime(workflow.next_run_at)}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {overview.data && (
            <p className="border-t border-white/[0.05] px-5 py-3 text-[10px] leading-relaxed text-mist-600">
              Publishing mode: <span className="text-mist-300">{String(overview.data.system.ai.provider)}</span> · scheduler{" "}
              {overview.data.system.worker.alive ? "online" : "offline"}
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}
