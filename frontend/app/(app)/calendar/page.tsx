"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Modal, Panel, Skeleton, toast } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { clockTime, toLocalInput } from "@/lib/format";
import type { CalendarEvent, Task } from "@/lib/types";

interface ProductivityStatus {
  google_configured: boolean;
  connected: boolean;
  redirect_uri: string;
}

export default function CalendarPage() {
  const status = useApi<ProductivityStatus>("/api/productivity/status");
  const events = useApi<{ connected: boolean; events: CalendarEvent[] }>("/api/productivity/events?days=14");
  const scheduled = useApi<{ tasks: Task[] }>("/api/tasks?status=scheduled&limit=100", { pollMs: 30000 });
  const upcoming = useApi<{ tasks: Task[] }>("/api/system/overview", { pollMs: 30000 });
  const [open, setOpen] = useState(false);

  const agenda = useMemo(() => {
    const buckets = new Map<string, { label: string; items: { time: string; title: string; kind: string; id?: string }[] }>();
    const push = (iso: string, entry: { time: string; title: string; kind: string; id?: string }) => {
      const date = new Date(iso);
      if (Number.isNaN(date.getTime())) return;
      const key = date.toISOString().slice(0, 10);
      if (!buckets.has(key)) {
        buckets.set(key, {
          label: date.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }),
          items: [],
        });
      }
      buckets.get(key)!.items.push(entry);
    };

    for (const task of scheduled.data?.tasks ?? []) {
      if (task.scheduled_for) push(task.scheduled_for, { time: clockTime(task.scheduled_for), title: task.title, kind: task.kind, id: task.id });
    }
    for (const event of events.data?.events ?? []) {
      if (event.start) push(event.start, { time: clockTime(event.start), title: event.summary, kind: "event", id: event.id });
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => ({
        key,
        label: value.label,
        items: value.items.sort((a, b) => a.time.localeCompare(b.time)),
      }));
  }, [scheduled.data, events.data]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Calendar</h2>
          <p className="text-xs text-mist-500">Reminders, scheduled runs and your Google Calendar in one agenda.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`chip ${status.data?.connected ? "border-good/25 bg-good/5 text-good" : "border-white/10 text-mist-500"}`}>
            Google {status.data?.connected ? "connected" : "not connected"}
          </span>
          <button onClick={() => setOpen(true)} className="btn-primary !py-1.5 text-[11px]">
            <Icon name="plus" className="h-3.5 w-3.5" /> New event
          </button>
        </div>
      </div>

      {!status.data?.connected && (
        <div className="flex flex-col gap-2 rounded-2xl border border-white/10 bg-white/[0.02] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-relaxed text-mist-400">
            Scheduled tasks and reminders below are real and stored in NOVA. Google Calendar events appear here once you
            connect an account.
          </p>
          <Link href="/integrations" className="btn-ghost shrink-0 !py-1.5 text-[11px]">Connect Google</Link>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Panel title="Next 14 days" subtitle="Tasks + calendar events">
          {status.loading && !status.data ? (
            <div className="space-y-2 p-4"><Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" /></div>
          ) : agenda.length === 0 ? (
            <EmptyState
              title="Nothing scheduled"
              description="Ask NOVA to “remind me tomorrow at 9am…” or schedule a task from the Tasks page."
              action={<Link href="/chat" className="btn-ghost !py-1.5 text-[11px]">Ask NOVA</Link>}
            />
          ) : (
            <div className="divide-y divide-white/[0.05]">
              {agenda.map((day) => (
                <div key={day.key} className="px-5 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-mist-500">{day.label}</p>
                  <ul className="mt-2 space-y-2">
                    {day.items.map((item, index) => (
                      <li key={`${day.key}-${index}`} className="flex items-start gap-3">
                        <span className="w-12 shrink-0 font-mono text-[11px] text-mist-500">{item.time}</span>
                        <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md border ${item.kind === "event" ? "border-violet/25 bg-violet/5 text-violet" : item.kind === "reminder" ? "border-accent/25 bg-accent/5 text-accent" : "border-white/10 text-mist-500"}`}>
                          <Icon name={item.kind === "event" ? "calendar" : item.kind === "reminder" ? "clock" : "tasks"} className="h-2.5 w-2.5" />
                        </span>
                        {item.id && item.kind !== "event" ? (
                          <Link href={`/tasks/${item.id}`} className="min-w-0 flex-1 truncate text-[12px] text-mist-200 hover:text-accent-soft">
                            {item.title}
                          </Link>
                        ) : (
                          <span className="min-w-0 flex-1 truncate text-[12px] text-mist-300">{item.title}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Reminders" subtitle="Delivered to dashboard + WhatsApp">
            {(scheduled.data?.tasks ?? []).filter((task) => task.kind === "reminder").length === 0 ? (
              <EmptyState title="No reminders" description="“Remind me at 9am to review the build” creates one instantly." />
            ) : (
              <ul className="divide-y divide-white/[0.05]">
                {(scheduled.data?.tasks ?? []).filter((task) => task.kind === "reminder").map((task) => (
                  <li key={task.id} className="flex items-center gap-3 px-5 py-3">
                    <Icon name="clock" className="h-4 w-4 text-accent" />
                    <div className="min-w-0 flex-1">
                      <Link href={`/tasks/${task.id}`} className="truncate text-[12px] text-mist-200 hover:text-accent-soft">{task.title}</Link>
                      <p className="text-[10px] text-mist-600">{task.scheduled_for ? new Date(task.scheduled_for).toUTCString() : "—"}</p>
                    </div>
                    <Badge status={task.status} />
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Meeting summaries" subtitle="Prepare context before an event">
            <div className="px-5 py-4">
              <p className="text-[11px] leading-relaxed text-mist-500">
                After connecting Google, ask NOVA: <span className="code">prepare tomorrow&apos;s agenda and suggest focus blocks</span>.
                It reads the calendar and proposes a plan without creating anything until you approve.
              </p>
              <Link href="/chat" className="btn-ghost mt-3 w-full !py-1.5 text-[11px]">Open chat</Link>
            </div>
          </Panel>
        </div>
      </div>

      <CreateEventModal open={open} onClose={() => setOpen(false)} connected={Boolean(status.data?.connected)} onCreated={() => events.refresh()} />
    </div>
  );
}

function CreateEventModal({
  open,
  onClose,
  connected,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  connected: boolean;
  onCreated: () => void;
}) {
  const [summary, setSummary] = useState("");
  const [start, setStart] = useState(toLocalInput());
  const [end, setEnd] = useState(toLocalInput(new Date(Date.now() + 3600_000).toISOString()));
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await post("/api/productivity/events", {
        summary,
        description,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
      });
      toast("Event created", "good");
      setSummary("");
      onCreated();
      onClose();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create event", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New calendar event"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={submit} disabled={busy || !summary.trim() || !connected} className="btn-primary">
            {busy ? "Creating…" : "Create event"}
          </button>
        </>
      }
    >
      {!connected && (
        <p className="mb-3 rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2 text-[11px] text-warn">
          Google Calendar is not connected. Connect it in Integrations first.
        </p>
      )}
      <div className="space-y-3">
        <div>
          <label className="label">Title</label>
          <input className="input" value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="Design review" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Starts</label>
            <input type="datetime-local" className="input" value={start} onChange={(event) => setStart(event.target.value)} />
          </div>
          <div>
            <label className="label">Ends</label>
            <input type="datetime-local" className="input" value={end} onChange={(event) => setEnd(event.target.value)} />
          </div>
        </div>
        <div>
          <label className="label">Notes</label>
          <textarea className="input min-h-[72px]" value={description} onChange={(event) => setDescription(event.target.value)} />
        </div>
      </div>
    </Modal>
  );
}
