"use client";

import Link from "next/link";
import { useState } from "react";
import { post } from "@/lib/api";
import { relativeTime, shortId, statusLabel } from "@/lib/format";
import type { Task } from "@/lib/types";
import { Icon } from "./icons";
import { Badge, Progress, toast } from "./ui";

export function TaskItem({
  task,
  onChange,
  compact = false,
}: {
  task: Task;
  onChange?: () => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const active = ["queued", "running", "planning"].includes(task.status);

  async function act(path: string, label: string) {
    setBusy(true);
    try {
      await post(`/api/tasks/${task.id}/${path}`);
      toast(label, "good");
      onChange?.();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Action failed", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="group border-b border-white/[0.05] px-4 py-3 last:border-0 hover:bg-white/[0.015] sm:px-5">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.02] text-mist-500">
          <Icon
            name={
              task.kind === "research"
                ? "research"
                : task.kind === "reminder"
                  ? "clock"
                  : task.kind.startsWith("youtube")
                    ? "youtube"
                    : task.kind === "instagram"
                      ? "instagram"
                      : task.kind === "email"
                        ? "emails"
                        : task.kind === "control"
                          ? "power"
                          : "tasks"
            }
            className="h-3.5 w-3.5"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Link href={`/tasks/${task.id}`} className="min-w-0 truncate text-[13px] font-medium text-mist-100 hover:text-accent-soft">
              {task.title || "Untitled task"}
            </Link>
            <Badge status={task.status} />
            {task.approval_required && task.status !== "waiting_approval" && (
              <span className="chip border-warn/25 bg-warn/5 text-[10px] text-warn">gated</span>
            )}
          </div>
          {!compact && task.current_step && task.status !== "completed" && (
            <p className="mt-1 truncate text-[11px] text-mist-500">{task.current_step}</p>
          )}
          {task.error && <p className="mt-1 line-clamp-2 text-[11px] text-bad/90">{task.error}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-mist-600">
            <span className="font-mono text-mist-500">{shortId(task.id)}</span>
            <span>{task.agent}</span>
            <span>{relativeTime(task.created_at)}</span>
            {task.scheduled_for && <span className="text-violet">for {relativeTime(task.scheduled_for)}</span>}
            {task.source !== "web" && <span className="uppercase tracking-wide">{task.source}</span>}
          </div>
          {task.status === "running" || task.status === "queued" || task.status === "waiting_approval" ? (
            <div className="mt-2.5 flex items-center gap-3">
              <Progress value={task.progress} tone={task.status === "waiting_approval" ? "warn" : "accent"} />
              <span className="w-8 text-right text-[10px] text-mist-500">{task.progress}%</span>
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1 opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100">
          {active && (
            <button
              disabled={busy}
              onClick={() => act("pause", "Task paused")}
              className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-warn"
              title="Pause"
            >
              <Icon name="clock" className="h-3.5 w-3.5" />
            </button>
          )}
          {task.status === "paused" && (
            <button
              disabled={busy}
              onClick={() => act("resume", "Task resumed")}
              className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-good"
              title="Resume"
            >
              <Icon name="play" className="h-3.5 w-3.5" />
            </button>
          )}
          {["failed", "cancelled"].includes(task.status) && (
            <button
              disabled={busy}
              onClick={() => act("retry", "Task re-queued")}
              className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-accent"
              title="Retry"
            >
              <Icon name="refresh" className="h-3.5 w-3.5" />
            </button>
          )}
          {!["completed", "failed", "cancelled"].includes(task.status) && (
            <button
              disabled={busy}
              onClick={() => act("cancel", "Task cancelled")}
              className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-bad"
              title="Cancel"
            >
              <Icon name="x" className="h-3.5 w-3.5" />
            </button>
          )}
          <Link href={`/tasks/${task.id}`} className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-mist-200" title="Details">
            <Icon name="arrow" className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
    </div>
  );
}

export function TaskList({
  tasks,
  onChange,
  compact,
  empty,
}: {
  tasks: Task[];
  onChange?: () => void;
  compact?: boolean;
  empty?: React.ReactNode;
}) {
  if (!tasks.length) return <>{empty}</>;
  return (
    <div>
      {tasks.map((task) => (
        <TaskItem key={task.id} task={task} onChange={onChange} compact={compact} />
      ))}
    </div>
  );
}

export { statusLabel };
