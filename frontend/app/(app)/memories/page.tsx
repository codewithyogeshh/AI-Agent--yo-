"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Modal, Panel, Skeleton, Tabs, toast } from "@/components/ui";
import { api, del, getToken, patch, post, useApi } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { MemoryItem } from "@/lib/types";

const KINDS = [
  { id: "all", label: "All" },
  { id: "preference", label: "Preferences" },
  { id: "fact", label: "Facts" },
  { id: "project", label: "Projects" },
  { id: "workflow", label: "Workflows" },
] as const;

export default function MemoriesPage() {
  const [kind, setKind] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 320);
    return () => window.clearTimeout(timer);
  }, [search]);

  const params = new URLSearchParams();
  if (kind !== "all") params.set("kind", kind);
  if (query) params.set("q", query);
  const memories = useApi<{ memories: MemoryItem[] }>(`/api/memory?${params.toString()}`, { pollMs: 30000 });

  async function remove(memory: MemoryItem) {
    if (!window.confirm(`Forget “${memory.title}”?`)) return;
    try {
      await del(`/api/memory/${memory.id}`);
      toast("Memory deleted", "good");
      memories.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Delete failed", "bad");
    }
  }

  async function exportAll() {
    try {
      const response = await fetch("/api/proxy/api/memory/export", {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "nova-memory.json";
      anchor.click();
      URL.revokeObjectURL(url);
      toast("Memory exported", "good");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Export failed", "bad");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Memories</h2>
          <p className="text-xs text-mist-500">What NOVA knows about you. You control every entry; secrets are refused.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={exportAll} className="btn-ghost !py-1.5 text-[11px]">
            <Icon name="download" className="h-3.5 w-3.5" /> Export
          </button>
          <button onClick={() => setCreating(true)} className="btn-primary !py-1.5 text-[11px]">
            <Icon name="plus" className="h-3.5 w-3.5" /> Add memory
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Tabs tabs={KINDS.map((item) => ({ ...item }))} value={kind as typeof KINDS[number]["id"]} onChange={(value) => setKind(value)} />
        <div className="relative sm:w-64">
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-mist-600" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search memories" className="input !py-2 pl-8 text-xs" />
        </div>
      </div>

      {memories.loading && !memories.data ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28 w-full" />)}
        </div>
      ) : (memories.data?.memories ?? []).length === 0 ? (
        <Panel>
          <EmptyState
            title="No memories yet"
            description="NOVA stores preferences, project context and recurring workflow details here. Add one manually or let the agent save it."
            action={<button onClick={() => setCreating(true)} className="btn-ghost !py-1.5 text-[11px]">Add the first memory</button>}
            icon={<Icon name="memories" className="h-5 w-5" />}
          />
        </Panel>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {(memories.data?.memories ?? []).map((memory) => (
            <div key={memory.id} className="panel panel-hover flex flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Badge status="info" label={memory.kind} />
                  <h3 className="mt-1.5 text-[13px] font-medium text-mist-100">{memory.title}</h3>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button onClick={() => setEditing(memory)} className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-mist-100" title="Edit">
                    <Icon name="edit" className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => remove(memory)} className="rounded-md p-1.5 text-mist-500 hover:bg-white/5 hover:text-bad" title="Forget">
                    <Icon name="trash" className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <p className="mt-2 line-clamp-4 whitespace-pre-line text-[11px] leading-relaxed text-mist-400">{memory.content}</p>
              <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
                {memory.tags.map((tag) => (
                  <span key={tag} className="chip border-white/[0.07] text-[9px] text-mist-600">#{tag}</span>
                ))}
                <span className="ml-auto text-[9px] text-mist-600">{relativeTime(memory.updated_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <MemoryModal
        open={creating || Boolean(editing)}
        memory={editing}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSaved={() => {
          memories.refresh();
          setCreating(false);
          setEditing(null);
        }}
      />
    </div>
  );
}

function MemoryModal({
  open,
  memory,
  onClose,
  onSaved,
}: {
  open: boolean;
  memory: MemoryItem | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("preference");
  const [tags, setTags] = useState("");
  const [importance, setImportance] = useState(2);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (memory) {
      setTitle(memory.title);
      setContent(memory.content);
      setKind(memory.kind);
      setTags(memory.tags.join(", "));
      setImportance(memory.importance);
    } else {
      setTitle("");
      setContent("");
      setKind("preference");
      setTags("");
      setImportance(2);
    }
  }, [memory, open]);

  async function save() {
    setBusy(true);
    const payload = { title, content, kind, tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean), importance };
    try {
      if (memory) await patch(`/api/memory/${memory.id}`, payload);
      else await post("/api/memory", payload);
      toast(memory ? "Memory updated" : "Memory saved", "good");
      onSaved();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Save failed", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={memory ? "Edit memory" : "Add memory"}
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={busy || !title.trim() || !content.trim()} className="btn-primary">
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="label">Title</label>
          <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Video style preference" />
        </div>
        <div>
          <label className="label">Content</label>
          <textarea className="input min-h-[110px]" value={content} onChange={(event) => setContent(event.target.value)} placeholder="Prefers vertical shorts with burned-in captions and a calm voice." />
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="label">Kind</label>
            <select className="input" value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="preference">Preference</option>
              <option value="fact">Fact</option>
              <option value="project">Project</option>
              <option value="workflow">Workflow</option>
            </select>
          </div>
          <div>
            <label className="label">Tags</label>
            <input className="input" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="video, style" />
          </div>
          <div>
            <label className="label">Importance</label>
            <select className="input" value={importance} onChange={(event) => setImportance(Number(event.target.value))}>
              <option value={3}>High</option>
              <option value={2}>Normal</option>
              <option value={1}>Low</option>
            </select>
          </div>
        </div>
        <p className="text-[10px] leading-relaxed text-mist-600">
          Passwords, API keys and payment details are rejected by the memory API by design.
        </p>
      </div>
    </Modal>
  );
}
