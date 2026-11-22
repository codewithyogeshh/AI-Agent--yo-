"use client";

import Link from "next/link";
import { useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Markdown, Panel, Skeleton, toast } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { relativeTime, shortId } from "@/lib/format";
import type { Task } from "@/lib/types";

export default function ResearchPage() {
  const research = useApi<{ tasks: Task[] }>("/api/tasks?kind=research&limit=30", { pollMs: 20000 });
  const [topic, setTopic] = useState("");
  const [angle, setAngle] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Task | null>(null);
  const detail = useApi<{ task: Task }>(selected ? `/api/tasks/${selected.id}` : null, { pollMs: 4000 });

  async function launch(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setBusy(true);
    try {
      const prompt = `Research ${topic}${angle ? ` with a focus on ${angle}` : ""}. Gather reliable sources and write a cited brief with key findings and next actions.`;
      const result = await post<{ task: Task }>("/api/tasks", { prompt });
      toast("Research started", "good");
      setTopic("");
      setAngle("");
      setSelected(result.task);
      research.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not start research", "bad");
    } finally {
      setBusy(false);
    }
  }

  const tasks = research.data?.tasks ?? [];
  const current = detail.data?.task ?? selected;

  return (
    <div className="space-y-4">
      <Panel title="New research brief" subtitle="Web search → source extraction → cited report">
        <form onSubmit={launch} className="grid gap-3 px-5 py-4 lg:grid-cols-[1.5fr_1fr_auto] lg:items-end">
          <div>
            <label className="label">Topic</label>
            <input className="input" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="e.g. open-source local LLM runtimes" />
          </div>
          <div>
            <label className="label">Focus (optional)</label>
            <input className="input" value={angle} onChange={(event) => setAngle(event.target.value)} placeholder="e.g. cost and hardware" />
          </div>
          <button type="submit" disabled={busy || !topic.trim()} className="btn-primary h-[42px]">
            {busy ? "Starting…" : "Research"}
            <Icon name="search" className="h-4 w-4" />
          </button>
        </form>
        <p className="border-t border-white/[0.05] px-5 py-2.5 text-[10px] leading-relaxed text-mist-600">
          Sources are fetched live. Without an AI provider the brief is an extractive digest with citations rather than rewritten prose.
        </p>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <Panel title="Briefs" subtitle={`${tasks.length} runs`}>
          {research.loading && !research.data ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : tasks.length === 0 ? (
            <EmptyState title="No research yet" description="Your briefs and citations will be listed here." />
          ) : (
            <ul className="max-h-[560px] divide-y divide-white/[0.05] overflow-y-auto">
              {tasks.map((task) => (
                <li key={task.id}>
                  <button
                    onClick={() => setSelected(task)}
                    className={`w-full px-4 py-3 text-left transition hover:bg-white/[0.02] ${current?.id === task.id ? "bg-accent/[0.06]" : ""}`}
                  >
                    <p className="line-clamp-2 text-[12px] text-mist-200">{task.title}</p>
                    <div className="mt-1 flex items-center gap-2">
                      <Badge status={task.status} />
                      <span className="text-[9px] text-mist-600">{relativeTime(task.created_at)}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          title={current ? current.title : "Report"}
          subtitle={current ? `${shortId(current.id)} · ${current.status}` : "Select a brief"}
          action={current ? <Link href={`/tasks/${current.id}`} className="text-[11px] text-mist-500 hover:text-accent-soft">Task →</Link> : undefined}
        >
          {!current ? (
            <EmptyState title="Nothing selected" description="Pick a research run to read its findings, or start a new one." icon={<Icon name="research" className="h-5 w-5" />} />
          ) : current.status !== "completed" ? (
            <div className="px-5 py-6">
              <p className="text-xs text-mist-400">{current.current_step || "Working…"}</p>
              <p className="mt-1 text-[10px] text-mist-600">{current.progress}% complete</p>
            </div>
          ) : (
            <div className="px-5 py-4">
              {(current.result?.summary ?? []).filter(Boolean).length ? (
                <Markdown content={(current.result?.summary ?? []).filter(Boolean).join("\n\n")} />
              ) : (
                <p className="text-xs text-mist-400">No summary captured.</p>
              )}
              {(current.result?.artifacts ?? []).length > 0 && (
                <div className="mt-4 border-t border-white/[0.06] pt-3">
                  <p className="label">Sources &amp; files</p>
                  <ul className="space-y-1.5">
                    {(current.result?.artifacts ?? []).map((artifact, index) => (
                      <li key={index} className="flex items-center gap-2 text-[11px]">
                        <Icon name={artifact.url ? "external" : "files"} className="h-3.5 w-3.5 text-mist-500" />
                        {artifact.url ? (
                          <a href={artifact.url} target="_blank" rel="noopener noreferrer" className="truncate text-accent-soft hover:underline">
                            {artifact.title || artifact.url}
                          </a>
                        ) : (
                          <span className="truncate text-mist-400">{artifact.title || artifact.path}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
