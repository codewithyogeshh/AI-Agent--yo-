"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Markdown, Panel, Progress, Skeleton, toast } from "@/components/ui";
import { assetUrl, del, post, useApi, useAssetToken, useEventStream } from "@/lib/api";
import { dateTime, duration, relativeTime, shortId, statusLabel } from "@/lib/format";
import type { Approval, Task, TaskEvent } from "@/lib/types";

interface TaskDetail {
  task: Task;
  events: TaskEvent[];
  approvals: Approval[];
}

const EVENT_STYLE: Record<string, { tone: string; icon: string }> = {
  step: { tone: "text-accent-soft border-accent/20 bg-accent/5", icon: "arrow" },
  result: { tone: "text-good border-good/20 bg-good/5", icon: "check" },
  completed: { tone: "text-good border-good/25 bg-good/10", icon: "check" },
  error: { tone: "text-bad border-bad/25 bg-bad/5", icon: "x" },
  retry: { tone: "text-warn border-warn/20 bg-warn/5", icon: "refresh" },
  approval: { tone: "text-warn border-warn/25 bg-warn/5", icon: "shield" },
  plan: { tone: "text-violet border-violet/20 bg-violet/5", icon: "spark" },
  status: { tone: "text-mist-400 border-white/10 bg-white/[0.02]", icon: "clock" },
  tool: { tone: "text-accent-soft border-accent/20 bg-accent/5", icon: "spark" },
  progress: { tone: "text-mist-400 border-white/10 bg-white/[0.02]", icon: "arrow" },
};

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [busy, setBusy] = useState("");
  const assetToken = useAssetToken();
  const detail = useApi<TaskDetail>(`/api/tasks/${params.id}`, { pollMs: 4000 });
  const logRef = useRef<HTMLDivElement>(null);
  const task = detail.data?.task;
  const live = useEventStream((event) => {
    if (event.task_id === params.id) detail.refresh();
  });

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [detail.data?.events?.length]);

  async function act(path: string, label: string) {
    setBusy(path);
    try {
      await post(`/api/tasks/${params.id}/${path}`);
      toast(label, "good");
      detail.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Action failed", "bad");
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    if (!window.confirm("Delete this task and its history?")) return;
    try {
      await del(`/api/tasks/${params.id}`);
      router.push("/tasks");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Delete failed", "bad");
    }
  }

  if (detail.loading && !task) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (detail.error || !task) {
    return (
      <Panel>
        <EmptyState
          title="Task not found"
          description={detail.error || "It may have been deleted."}
          action={<Link href="/tasks" className="btn-ghost !py-1.5 text-[11px]">Back to tasks</Link>}
        />
      </Panel>
    );
  }

  const result = task.result ?? {};
  const artifacts = result.artifacts ?? [];
  const running = ["queued", "running", "planning"].includes(task.status);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-[11px] text-mist-500">
        <Link href="/tasks" className="hover:text-accent-soft">Tasks</Link>
        <span>/</span>
        <span className="font-mono">{shortId(task.id)}</span>
        {live && <span className="ml-1 flex items-center gap-1 text-good"><span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-good" />live</span>}
      </div>

      <div className="panel p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge status={task.status} />
              <span className="chip border-white/10 text-[10px] uppercase tracking-wide text-mist-500">{task.agent}</span>
              <span className="chip border-white/10 text-[10px] text-mist-500">{task.source}</span>
              {task.recurrence && <span className="chip border-violet/25 bg-violet/5 text-[10px] text-violet">repeats {task.recurrence}</span>}
            </div>
            <h2 className="mt-2 text-lg font-semibold tracking-tight text-mist-100">{task.title}</h2>
            <p className="mt-1 max-w-3xl whitespace-pre-line text-xs leading-relaxed text-mist-400">{task.prompt}</p>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[10px] text-mist-600">
              <span>created {relativeTime(task.created_at)}</span>
              {task.started_at && <span>started {relativeTime(task.started_at)}</span>}
              {task.finished_at && <span>finished {relativeTime(task.finished_at)}</span>}
              {task.duration_seconds !== null && <span>took {duration(task.duration_seconds)}</span>}
              {task.scheduled_for && <span className="text-violet">scheduled {dateTime(task.scheduled_for)}</span>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {running && (
              <button onClick={() => act("pause", "Paused")} disabled={busy !== ""} className="btn-ghost !py-1.5 text-[11px]">
                <Icon name="clock" className="h-3.5 w-3.5" /> Pause
              </button>
            )}
            {task.status === "paused" && (
              <button onClick={() => act("resume", "Resumed")} disabled={busy !== ""} className="btn-primary !py-1.5 text-[11px]">
                <Icon name="play" className="h-3.5 w-3.5" /> Resume
              </button>
            )}
            {["failed", "cancelled"].includes(task.status) && (
              <button onClick={() => act("retry", "Re-queued")} disabled={busy !== ""} className="btn-ghost !py-1.5 text-[11px]">
                <Icon name="refresh" className="h-3.5 w-3.5" /> Retry
              </button>
            )}
            {!["completed", "failed", "cancelled"].includes(task.status) && (
              <button onClick={() => act("cancel", "Cancelled")} disabled={busy !== ""} className="btn-danger !py-1.5 text-[11px]">
                <Icon name="x" className="h-3.5 w-3.5" /> Cancel
              </button>
            )}
            {["completed", "failed", "cancelled"].includes(task.status) && (
              <button onClick={remove} className="btn-ghost !py-1.5 text-[11px] text-bad">
                <Icon name="trash" className="h-3.5 w-3.5" /> Delete
              </button>
            )}
          </div>
        </div>

        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between text-[11px] text-mist-500">
            <span>{task.current_step || statusLabel(task.status)}</span>
            <span>{task.progress}%</span>
          </div>
          <Progress
            value={task.progress}
            tone={task.status === "failed" ? "bad" : task.status === "waiting_approval" ? "warn" : task.status === "completed" ? "good" : "accent"}
          />
        </div>

        {task.error && (
          <div className="mt-4 rounded-xl border border-bad/25 bg-bad/[0.06] px-4 py-3 text-xs leading-relaxed text-bad/90">
            {task.error}
          </div>
        )}
        {task.status === "completed" && result.verified === false && (
          <div className="mt-4 rounded-xl border border-warn/25 bg-warn/[0.06] px-4 py-3 text-xs text-warn">
            Completed with unverified results — check the artifacts before relying on them.
          </div>
        )}
      </div>

      {(detail.data?.approvals ?? []).length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-warn">Waiting for you</h3>
          {(detail.data?.approvals ?? []).map((approval) => (
            <ApprovalCard key={approval.id} approval={{ ...approval, task_title: task.title }} onChange={detail.refresh} />
          ))}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.25fr_1fr]">
        <Panel title="Execution plan" subtitle={`${(task.plan ?? []).length} steps`}>
          <ol className="relative">
            {(task.plan ?? []).map((step, index) => {
              const done = step.status === "done";
              const failed = step.status === "failed" || step.status === "rejected";
              const waiting = step.status === "waiting_approval";
              const active = step.status === "running";
              return (
                <li key={index} className="relative flex gap-3 border-b border-white/[0.04] px-5 py-3.5 last:border-0">
                  <div className="flex flex-col items-center">
                    <span
                      className={`grid h-6 w-6 place-items-center rounded-full border text-[10px] font-semibold ${
                        done
                          ? "border-good/40 bg-good/10 text-good"
                          : failed
                            ? "border-bad/40 bg-bad/10 text-bad"
                            : waiting
                              ? "border-warn/40 bg-warn/10 text-warn"
                              : active
                                ? "border-accent/50 bg-accent/15 text-accent"
                                : "border-white/12 bg-white/[0.02] text-mist-500"
                      }`}
                    >
                      {done ? <Icon name="check" className="h-3 w-3" /> : failed ? <Icon name="x" className="h-3 w-3" /> : index + 1}
                    </span>
                    {index < (task.plan?.length ?? 0) - 1 && <span className="mt-1 w-px flex-1 bg-white/[0.07]" />}
                  </div>
                  <div className="min-w-0 flex-1 pb-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-[12px] font-medium text-mist-200">{step.label}</p>
                      <span className="code">{step.tool}</span>
                      {step.approved && <span className="chip border-good/25 bg-good/5 text-[9px] text-good">approved</span>}
                      {step.verified === false && step.status === "done" && (
                        <span className="chip border-warn/25 bg-warn/5 text-[9px] text-warn">unverified</span>
                      )}
                    </div>
                    {step.error && <p className="mt-1 text-[11px] text-bad/90">{step.error}</p>}
                    {step.output && Object.keys(step.output).length > 0 && (
                      <details className="mt-1.5">
                        <summary className="cursor-pointer text-[10px] text-mist-600 hover:text-mist-400">step output</summary>
                        <pre className="mt-1.5 max-h-40 overflow-auto rounded-lg bg-ink-950/60 p-2.5 font-mono text-[10px] leading-relaxed text-mist-400">
                          {JSON.stringify(step.output, null, 2).slice(0, 4000)}
                        </pre>
                      </details>
                    )}
                  </div>
                </li>
              );
            })}
            {!(task.plan ?? []).length && <EmptyState title="No plan stored" description="This task was applied directly (control command or reminder)." />}
          </ol>
        </Panel>

        <div className="space-y-4">
          <Panel title="Result" subtitle={result.verified === false ? "unverified" : "verified"}>
            <div className="space-y-3 px-5 py-4">
              {(result.summary ?? []).filter(Boolean).length > 0 ? (
                <Markdown content={(result.summary ?? []).filter(Boolean).join("\n\n")} />
              ) : (
                <p className="text-xs text-mist-500">No summary recorded yet.</p>
              )}
              {artifacts.length > 0 && (
                <div>
                  <p className="label mt-3">Artifacts</p>
                  <ul className="space-y-1.5">
                    {artifacts.map((artifact, index) => {
                      const href =
                        artifact.url ||
                        (artifact.path && assetToken
                          ? assetUrl(`/api/files/artifact?path=${encodeURIComponent(artifact.path)}`, assetToken)
                          : "");
                      return (
                        <li key={index} className="flex items-center gap-2 text-[11px]">
                          <Icon
                            name={artifact.kind === "video" ? "film" : artifact.kind === "image" ? "library" : artifact.kind === "link" ? "external" : "files"}
                            className="h-3.5 w-3.5 shrink-0 text-mist-500"
                          />
                          {href ? (
                            <a href={href} target="_blank" rel="noopener noreferrer" className="truncate text-accent-soft hover:underline">
                              {artifact.title || artifact.path?.split("/").pop()}
                            </a>
                          ) : (
                            <span className="truncate text-mist-400">{artifact.title || artifact.path || artifact.kind}</span>
                          )}
                          <span className="ml-auto shrink-0 text-[9px] uppercase tracking-wide text-mist-600">{artifact.kind}</span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </div>
          </Panel>

          <Panel title="Event log" subtitle="Persisted, ordered, replayable">
            <div ref={logRef} className="max-h-[420px] space-y-2 overflow-y-auto px-4 py-3">
              {(detail.data?.events ?? []).map((event) => {
                const style = EVENT_STYLE[event.type] ?? EVENT_STYLE.status;
                return (
                  <div key={event.id} className="flex gap-2.5">
                    <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md border ${style.tone}`}>
                      <Icon name={style.icon} className="h-2.5 w-2.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="whitespace-pre-line break-words text-[11px] leading-relaxed text-mist-300">{event.message}</p>
                      <p className="mt-0.5 text-[9px] text-mist-600">{event.type} · {relativeTime(event.created_at)}</p>
                    </div>
                  </div>
                );
              })}
              {(detail.data?.events ?? []).length === 0 && (
                <p className="py-6 text-center text-[11px] text-mist-500">No events yet.</p>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
