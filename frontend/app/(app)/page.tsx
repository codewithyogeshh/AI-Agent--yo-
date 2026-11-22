"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ContentCard } from "@/components/ContentCard";
import { Icon } from "@/components/icons";
import { TaskList } from "@/components/TaskItem";
import { Badge, EmptyState, Panel, Skeleton, Stat, toast } from "@/components/ui";
import { post, useApi, useEventStream } from "@/lib/api";
import { bytes, dateTime, relativeTime } from "@/lib/format";

import type { Approval, ContentItem, Overview } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const overview = useApi<Overview>("/api/system/overview", { pollMs: 15000 });
  const approvals = useApi<{ approvals: Approval[] }>("/api/approvals?status=pending", { pollMs: 15000 });
  const [prompt, setPrompt] = useState("");
  const [creating, setCreating] = useState(false);

  const connected = useEventStream((event) => {
    if (["completed", "failed", "approval", "step", "status"].includes(event.type)) {
      overview.refresh();
      approvals.refresh();
    }
  });

  const refresh = useCallback(() => {
    overview.refresh();
    approvals.refresh();
  }, [overview, approvals]);

  async function quickTask(event: React.FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || creating) return;
    setCreating(true);
    try {
      const result = await post<{ task: { id: string } }>("/api/tasks", { prompt });
      toast("Task accepted — NOVA is planning it now", "good");
      setPrompt("");
      router.push(`/tasks/${result.task.id}`);
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create task", "bad");
    } finally {
      setCreating(false);
    }
  }

  const data = overview.data;
  const maxDaily = useMemo(
    () => Math.max(1, ...(data?.daily ?? []).map((day) => Math.max(day.created, day.completed))),
    [data]
  );
  const pendingApprovals = approvals.data?.approvals ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-mist-500">Command center</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-mist-100 sm:text-2xl">
            What should NOVA handle?
          </h2>
          <p className="mt-1 text-xs text-mist-500">
            {data ? `${data.stats.active} active · ${data.system.queue_depth} queued · worker ${data.system.worker.alive ? "healthy" : "stopped"}` : "Loading state…"}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className={`chip ${connected ? "border-good/25 bg-good/5 text-good" : "border-white/10 text-mist-500"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${connected ? "animate-pulse-soft bg-good" : "bg-mist-600"}`} />
            {connected ? "Live event stream" : "Polling"}
          </span>
        </div>
      </div>

      <form onSubmit={quickTask} className="panel flex items-center gap-2 p-2 shadow-glow">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent">
          <Icon name="spark" className="h-4 w-4" />
        </span>
        <input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Research vector DBs, make a 60s Short, summarise my inbox, remind me at 9am…"
          className="min-w-0 flex-1 bg-transparent px-1 text-sm text-mist-100 placeholder:text-mist-500 focus:outline-none"
        />
        <button type="submit" disabled={creating || !prompt.trim()} className="btn-primary shrink-0">
          {creating ? "Planning…" : "Assign"}
          <Icon name="arrow" className="h-4 w-4" />
        </button>
      </form>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {overview.loading && !data
          ? Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="panel px-5 py-4">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="mt-3 h-7 w-12" />
              </div>
            ))
          : data && (
              <>
                <Stat label="Active now" value={data.stats.active} hint={`${data.system.queue_depth} in queue`} tone="accent" icon={<Icon name="play" className="h-4 w-4" />} />
                <Stat label="Awaiting you" value={data.stats.pending_approvals} hint="approvals to review" tone={data.stats.pending_approvals ? "warn" : "default"} icon={<Icon name="shield" className="h-4 w-4" />} />
                <Stat label="Done this week" value={data.stats.completed_week} hint={`${data.stats.failed_week} failed`} tone="good" icon={<Icon name="check" className="h-4 w-4" />} />
                <Stat label="Content drafts" value={data.stats.content_drafts} hint="ready to review" icon={<Icon name="film" className="h-4 w-4" />} />
              </>
            )}
      </div>

      {data?.system.ai.offline_mode && (
        <div className="flex flex-col gap-3 rounded-2xl border border-warn/25 bg-warn/[0.06] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2.5">
            <Icon name="spark" className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            <p className="text-xs leading-relaxed text-mist-300">
              <span className="font-medium text-warn">Offline planner mode.</span> NOVA is executing with real tools and a
              deterministic planner. Add an AI provider key for written scripts, summaries and smarter planning.
            </p>
          </div>
          <Link href="/settings" className="btn-ghost shrink-0 !py-1.5 text-[11px]">
            Configure AI
          </Link>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel
          title="Active & recent tasks"
          subtitle="Live progress from the worker"
          action={
            <Link href="/tasks" className="text-[11px] text-mist-500 hover:text-accent-soft">
              All tasks →
            </Link>
          }
        >
          {overview.loading && !data ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-2/3" />
            </div>
          ) : (
            <TaskList
              tasks={data?.recent_tasks ?? []}
              onChange={refresh}
              empty={
                <EmptyState
                  title="No tasks yet"
                  description="Assign something above, or send an instruction from WhatsApp once it is connected."
                  action={
                    <Link href="/chat" className="btn-ghost !py-1.5 text-[11px]">
                      Open AI chat
                    </Link>
                  }
                />
              }
            />
          )}
        </Panel>

        <Panel
          title="Approvals"
          subtitle="Actions waiting on your explicit consent"
          action={<span className="chip border-warn/25 bg-warn/5 text-[10px] text-warn">{pendingApprovals.length} pending</span>}
        >
          {pendingApprovals.length === 0 ? (
            <EmptyState
              title="Nothing needs approval"
              description="Publishing, sending mail and desktop commands always pause here first."
              icon={<Icon name="shield" className="h-5 w-5" />}
            />
          ) : (
            <div className="space-y-3 p-4">
              {pendingApprovals.slice(0, 3).map((approval) => (
                <ApprovalCard key={approval.id} approval={approval} onChange={refresh} />
              ))}
              {pendingApprovals.length > 3 && (
                <Link href="/tasks?status=waiting_approval" className="block text-center text-[11px] text-mist-500 hover:text-accent-soft">
                  {pendingApprovals.length - 3} more →
                </Link>
              )}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel title="Last 7 days" subtitle="Created vs completed">
          <div className="px-5 pb-5 pt-4">
            <div className="flex h-32 items-end gap-2 sm:gap-4">
              {(data?.daily ?? []).map((day) => (
                <div key={day.date} className="flex flex-1 flex-col items-center gap-2">
                  <div className="flex h-24 w-full items-end justify-center gap-1">
                    <div
                      className="w-1/3 rounded-t bg-white/[0.08]"
                      style={{ height: `${Math.max(3, (day.created / maxDaily) * 100)}%` }}
                      title={`${day.created} created`}
                    />
                    <div
                      className="w-1/3 rounded-t bg-accent/70"
                      style={{ height: `${Math.max(3, (day.completed / maxDaily) * 100)}%` }}
                      title={`${day.completed} completed`}
                    />
                  </div>
                  <span className="text-[9px] text-mist-600">
                    {new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined, { weekday: "short" })}
                  </span>
                </div>
              ))}
              {!data && <Skeleton className="h-full w-full" />}
            </div>
            <div className="mt-3 flex items-center gap-4 text-[10px] text-mist-500">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-white/[0.15]" /> created</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-accent" /> completed</span>
            </div>
          </div>
        </Panel>

        <Panel title="System" subtitle="Subsystems and connections">
          <div className="divide-y divide-white/[0.05]">
            <HealthRow
              label="Task worker"
              ok={Boolean(data?.system.worker.alive)}
              detail={data ? `${data.system.worker.running}/${data.system.worker.concurrency} running · ${data.system.worker.processed} processed` : ""}
            />
            <HealthRow
              label="AI provider"
              ok={Boolean(data?.system.ai.configured)}
              detail={data ? (data.system.ai.configured ? `${data.system.ai.provider} · ${data.system.ai.model}` : "offline planner") : ""}
              warnIfBad
            />
            <HealthRow
              label="Video renderer"
              ok={Boolean(data?.system.media.ffmpeg)}
              detail={data ? (data.system.media.ffmpeg ? "ffmpeg ready" : "ffmpeg missing") : ""}
              warnIfBad
            />
            <HealthRow
              label="Database"
              ok={true}
              detail={data ? `${data.system.storage.database_url_kind} · ${bytes(data.system.storage.free_bytes)} free` : ""}
            />
            <div className="px-5 py-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-mist-400">Integrations</span>
                <Link href="/integrations" className="text-[10px] text-mist-500 hover:text-accent-soft">manage →</Link>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(data?.system.integrations ?? []).map((integration) => (
                  <span key={integration.id} className={`chip ${integration.status === "connected" ? "border-good/25 bg-good/5 text-good" : integration.status === "error" ? "border-bad/25 bg-bad/5 text-bad" : "border-white/10 text-mist-500"}`}>
                    {integration.name.split(" · ")[0]}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel
          title="Latest content"
          subtitle="Rendered packages from the studio"
          action={<Link href="/library" className="text-[11px] text-mist-500 hover:text-accent-soft">Library →</Link>}
        >
          {data?.latest_content?.length ? (
            <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
              {(data.latest_content as ContentItem[]).map((item) => (
                <ContentCard key={item.id} item={item} onChange={refresh} />
              ))}
            </div>
          ) : (
            <EmptyState
              title="No content produced yet"
              description="Ask for a Short or Reel and NOVA will script, render, subtitle and thumbnail it."
              action={<Link href="/studio" className="btn-ghost !py-1.5 text-[11px]">Open studio</Link>}
            />
          )}
        </Panel>

        <Panel title="Upcoming" subtitle="Scheduled tasks and reminders">
          {data?.upcoming?.length ? (
            <ul className="divide-y divide-white/[0.05]">
              {data.upcoming.map((task) => (
                <li key={task.id} className="flex items-start gap-3 px-5 py-3">
                  <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-violet/20 bg-violet/5 text-violet">
                    <Icon name="clock" className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <Link href={`/tasks/${task.id}`} className="truncate text-[12px] text-mist-200 hover:text-accent-soft">
                      {task.title}
                    </Link>
                    <p className="mt-0.5 text-[10px] text-mist-600">{dateTime(task.scheduled_for)} · {relativeTime(task.scheduled_for)}</p>
                  </div>
                  <Badge status={task.status} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nothing scheduled" description="“Remind me tomorrow at 9am…” creates one instantly." />
          )}
        </Panel>
      </div>
    </div>
  );
}

function HealthRow({ label, ok, detail, warnIfBad }: { label: string; ok: boolean; detail: string; warnIfBad?: boolean }) {
  const tone = ok ? "bg-good" : warnIfBad ? "bg-warn" : "bg-bad";
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-3.5">
      <div className="flex items-center gap-2.5">
        <span className={`h-1.5 w-1.5 rounded-full ${tone} ${ok ? "" : "animate-pulse-soft"}`} />
        <span className="text-xs text-mist-300">{label}</span>
      </div>
      <span className="max-w-[55%] truncate text-right text-[10px] text-mist-600">{detail}</span>
    </div>
  );
}
