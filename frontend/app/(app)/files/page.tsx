"use client";

import { useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { EmptyState, Modal, Panel, Skeleton, toast } from "@/components/ui";
import { api, assetUrl, getToken, useApi, useAssetToken } from "@/lib/api";
import { bytes, relativeTime } from "@/lib/format";
import type { FileEntry } from "@/lib/types";

interface FilesResponse {
  path: string;
  entries: FileEntry[];
  assets: { id: string; name: string; kind: string; size: number; created_at: string | null }[];
}

export default function FilesPage() {
  const [path, setPath] = useState("");
  const files = useApi<FilesResponse>(`/api/files?path=${encodeURIComponent(path)}`, { pollMs: 30000 });
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const token = useAssetToken();

  const crumbs = path.split("/").filter(Boolean);

  async function open(entry: FileEntry) {
    if (entry.type === "dir") {
      setPath(entry.path);
      return;
    }
    if (!entry.previewable) {
      toast("Preview is only available for text and markdown files", "info");
      return;
    }
    try {
      const result = await api<{ content: string }>(`/api/files/content?path=${encodeURIComponent(entry.path)}`);
      setPreview({ path: entry.path, content: result.content });
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not read file", "bad");
    }
  }

  async function upload(file: File) {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      await api(`/api/files/upload?path=${encodeURIComponent(path)}`, { method: "POST", body: form });
      toast(`Uploaded ${file.name}`, "good");
      files.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Upload failed", "bad");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Files</h2>
          <p className="text-xs text-mist-500">Sandboxed workspace. NOVA cannot read anything outside this folder.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => inputRef.current?.click()} disabled={uploading} className="btn-ghost !py-1.5 text-[11px]">
            <Icon name="plus" className="h-3.5 w-3.5" /> {uploading ? "Uploading…" : "Upload"}
          </button>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload(file);
              event.target.value = "";
            }}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <button onClick={() => setPath("")} className={`rounded-md px-2 py-1 hover:bg-white/5 ${path === "" ? "text-accent-soft" : "text-mist-500"}`}>
          workspace
        </button>
        {crumbs.map((crumb, index) => {
          const target = crumbs.slice(0, index + 1).join("/");
          return (
            <span key={target} className="flex items-center gap-1.5">
              <span className="text-mist-700">/</span>
              <button onClick={() => setPath(target)} className={`rounded-md px-2 py-1 hover:bg-white/5 ${index === crumbs.length - 1 ? "text-accent-soft" : "text-mist-500"}`}>
                {crumb}
              </button>
            </span>
          );
        })}
      </div>

      <Panel>
        {files.loading && !files.data ? (
          <div className="space-y-2 p-4"><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
        ) : (files.data?.entries ?? []).length === 0 ? (
          <EmptyState
            title="This folder is empty"
            description="Reports, scripts, renders and uploads created by NOVA will appear here."
            action={<button onClick={() => inputRef.current?.click()} className="btn-ghost !py-1.5 text-[11px]">Upload a file</button>}
          />
        ) : (
          <ul className="divide-y divide-white/[0.04]">
            {(files.data?.entries ?? []).map((entry) => (
              <li key={entry.path} className="group flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.015]">
                <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg border ${entry.type === "dir" ? "border-accent/20 bg-accent/5 text-accent" : "border-white/[0.07] text-mist-500"}`}>
                  <Icon name={entry.type === "dir" ? "folder" : "files"} className="h-3.5 w-3.5" />
                </span>
                <button onClick={() => open(entry)} className="min-w-0 flex-1 truncate text-left text-[12px] text-mist-200 hover:text-accent-soft">
                  {entry.name}
                </button>
                <span className="hidden shrink-0 text-[10px] text-mist-600 sm:block">{entry.type === "dir" ? "folder" : bytes(entry.size)}</span>
                <span className="hidden w-20 shrink-0 text-right text-[10px] text-mist-600 sm:block">{relativeTime(entry.modified)}</span>
                {entry.type === "file" && token && (
                  <a
                    href={assetUrl(`/api/files/artifact?path=${encodeURIComponent(`${path ? `${path}/` : ""}${entry.name}`)}`, token)}
                    className="rounded-md p-1.5 text-mist-500 opacity-0 transition hover:bg-white/5 hover:text-accent-soft group-hover:opacity-100"
                    title="Download"
                  >
                    <Icon name="download" className="h-3.5 w-3.5" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Recorded assets" subtitle="Tracked by the media system">
        {(files.data?.assets ?? []).length === 0 ? (
          <EmptyState title="Nothing recorded" description="Generated media and documents are indexed here." />
        ) : (
          <div className="flex flex-wrap gap-2 p-4">
            {(files.data?.assets ?? []).slice(0, 40).map((asset) => (
              <span key={asset.id} className="chip border-white/10 text-[10px] text-mist-400">
                {asset.name} · {bytes(asset.size)}
              </span>
            ))}
          </div>
        )}
      </Panel>

      <Modal open={Boolean(preview)} onClose={() => setPreview(null)} title={preview?.path ?? ""} width="max-w-2xl">
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border border-white/[0.06] bg-ink-950/70 p-4 font-mono text-[11px] leading-relaxed text-mist-300">
          {preview?.content ?? ""}
        </pre>
        <p className="mt-2 text-[10px] text-mist-600">Read-only preview. Editing happens through NOVA&apos;s file tools.</p>
        <div className="mt-3">
          <a
            className="btn-ghost !py-1.5 text-[11px]"
            href={preview && token ? assetUrl(`/api/files/artifact?path=${encodeURIComponent(preview.path)}`, token) : "#"}
          >
            <Icon name="download" className="h-3.5 w-3.5" /> Download
          </a>
        </div>
      </Modal>
    </div>
  );
}
