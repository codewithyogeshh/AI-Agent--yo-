"use client";

import { useEffect, useMemo, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Icon } from "@/components/icons";
import { TaskList } from "@/components/TaskItem";
import { EmptyState, Modal, Panel, Skeleton, Tabs, toast } from "@/components/ui";
import { post, useApi, useEventStream } from "@/lib/api";
import { toLocalInput } from "@/lib/format";
import type { Approval, Task } from "@/lib/types";

const TABS = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "waiting_approval", label: "Approvals" },
  { id: "scheduled", label: "Scheduled" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function TasksPage() {
  const [tab, setTab] = useState<TabId>("all");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  // Read the filter from the URL on mount (avoids the useSearchParams Suspense requirement).
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("status") as TabId | null;
    if (requested && TABS.some((item) => item.id === requested)) setTab(requested);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 320);
    return () => window.clearTimeout(timer);
  }, [search]);

  const statusParam =
    tab === "all" ? "" : tab === "active" ? "queued" : tab === "waiting_approval" ? "waiting_approval" : tab;
  const listPath =
    tab === "active"
      ? `/api/tasks${query ? `?q=${encodeURIComponent(query)}` : ""}`
      : `/api/tasks?status=${statusParam}${query ? `&q=${encodeURIComponent(query)}` : ""}`;
  const tasks = useApi<{ tasks: Task[] }>(listPath, { pollMs: 8000 });
  const approvals = useApi<{ approvals: Approval[] }>("/api/approvals?status=pending", { pollMs: 8000 });

  useEventStream((event) => {
    if (["completed", "failed", "approval", "step", "status"].includes(event.type)) {
      tasks.refresh();
      approvals.refresh();
    }
  });

  const visibleTasks = useMemo(() => {
    const all = tasks.data?.tasks ?? [];
    if (tab !== "active") return all;
    return all.filter((task) => ["pending", "planning", "queued", "running", "waiting_approval"].includes(task.status));
  }, [tasks.data, tab]);

  const counts = {
    active: visibleTasks.filter((task) => ["pending", "planning", "queued", "running"].includes(task.status)).length,
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Tasks</h2>
          <p className="text-xs text-mist-500">Every task is planned, executed and verified step by step.</p>
        </div>
        <button onClick={() => setOpen(true)} className="btn-primary">
          <Icon name="plus" className="h-4 w-4" /> New task
        </button>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Tabs
          tabs={TABS.map((item) => ({
            ...item,
            count: item.id === "waiting_approval" ? approvals.data?.approvals.length : undefined,
          }))}
          value={tab}
          onChange={(value) => setTab(value)}
        />
        <div className="relative sm:w-64">
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-mist-600" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search tasks"
            className="input !py-2 pl-8 text-xs"
          />
        </div>
      </div>

      {tab === "waiting_approval" && (
        <div className="grid gap-3 lg:grid-cols-2">
          {(approvals.data?.approvals ?? []).map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} onChange={() => { approvals.refresh(); tasks.refresh(); }} />
          ))}
          {!approvals.loading && (approvals.data?.approvals ?? []).length === 0 && (
            <Panel className="lg:col-span-2">
              <EmptyState
                title="No pending approvals"
                description="Publishing, outbound email and desktop commands pause here until you approve them."
                icon={<Icon name="shield" className="h-5 w-5" />}
              />
            </Panel>
          )}
        </div>
      )}

      <Panel>
        {tasks.loading && !tasks.data ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-3/4" />
          </div>
        ) : tasks.error ? (
          <EmptyState title="Could not load tasks" description={tasks.error} />
        ) : tab === "waiting_approval" ? (
          visibleTasks.length > 0 ? (
            <TaskList tasks={visibleTasks} onChange={() => tasks.refresh()} />
          ) : null
        ) : (
          <TaskList
            tasks={visibleTasks}
            onChange={() => tasks.refresh()}
            empty={
              <EmptyState
                title="Nothing here"
                description={counts.active === 0 ? "Assign a task and it will appear here with live step-by-step progress." : "No tasks match this filter."}
                action={<button onClick={() => setOpen(true)} className="btn-ghost !py-1.5 text-[11px]">Create a task</button>}
              />
            }
          />
        )}
      </Panel>

      <NewTaskModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={() => {
          tasks.refresh();
          setOpen(false);
        }}
      />
    </div>
  );
}

function NewTaskModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState(2);
  const [schedule, setSchedule] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!prompt.trim()) return;
    setBusy(true);
    try {
      await post("/api/tasks", {
        prompt,
        title,
        priority,
        scheduled_for: schedule ? new Date(schedule).toISOString() : null,
        recurrence,
      });
      toast("Task queued", "good");
      setPrompt("");
      setTitle("");
      setSchedule("");
      setRecurrence("");
      onCreated();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create task", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New task"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={submit} disabled={busy || !prompt.trim()} className="btn-primary">
            {busy ? "Queueing…" : "Assign to NOVA"}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="label">Instruction</label>
          <textarea
            className="input min-h-[96px] resize-y"
            placeholder="e.g. Research the top 5 AI coding tools and write a brief with sources"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </div>
        <div>
          <label className="label">Title override (optional)</label>
          <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Auto-generated from the instruction" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Priority</label>
            <select className="input" value={priority} onChange={(event) => setPriority(Number(event.target.value))}>
              <option value={1}>High</option>
              <option value={2}>Normal</option>
              <option value={3}>Low</option>
            </select>
          </div>
          <div>
            <label className="label">Repeat</label>
            <select className="input" value={recurrence} onChange={(event) => setRecurrence(event.target.value)}>
              <option value="">Once</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </div>
        </div>
        <div>
          <label className="label">Schedule for (optional)</label>
          <input
            type="datetime-local"
            className="input"
            value={schedule}
            onChange={(event) => setSchedule(event.target.value)}
            min={toLocalInput()}
          />
          <p className="mt-1 text-[10px] text-mist-600">Leave empty to run as soon as a worker slot is free.</p>
        </div>
      </form>
    </Modal>
  );
}
