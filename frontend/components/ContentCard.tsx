"use client";

import { useState } from "react";
import { assetUrl, post, useAssetToken } from "@/lib/api";
import { dateTime, duration, relativeTime } from "@/lib/format";
import type { ContentItem } from "@/lib/types";
import { Icon } from "./icons";
import { Badge, toast } from "./ui";

export function ContentCard({ item, onChange }: { item: ContentItem; onChange?: () => void }) {
  const [open, setOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const token = useAssetToken();

  async function publish() {
    setPublishing(true);
    try {
      await post(`/api/content/${item.id}/publish`, { privacy: "private" });
      toast("Publish request queued — approve it on the dashboard", "good");
      onChange?.();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Publish failed", "bad");
    } finally {
      setPublishing(false);
    }
  }

  return (
    <>
      <div className="panel panel-hover group overflow-hidden">
        <button onClick={() => setOpen(true)} className="relative block aspect-[9/13] w-full overflow-hidden bg-ink-950">
          {item.thumb_url && token ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={assetUrl(item.thumb_url, token)}
              alt={item.title}
              className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
            />
          ) : (
            <div className="grid h-full place-items-center text-mist-600">
              <Icon name={item.platform === "instagram" ? "instagram" : "film"} className="h-8 w-8" />
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-950 via-ink-950/60 to-transparent p-3">
            <div className="flex items-center justify-between gap-2">
              <Badge status={item.status} />
              {item.duration_seconds ? <span className="text-[10px] text-mist-400">{duration(item.duration_seconds)}</span> : null}
            </div>
          </div>
          {item.has_video && (
            <span className="absolute left-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-ink-950/80 text-accent">
              <Icon name="play" className="h-3.5 w-3.5" />
            </span>
          )}
        </button>
        <div className="px-4 py-3">
          <p className="line-clamp-2 text-[13px] font-medium text-mist-100">{item.title}</p>
          <div className="mt-1.5 flex items-center justify-between text-[10px] text-mist-600">
            <span className="uppercase tracking-wide">{item.platform} · {item.kind}</span>
            <span>{relativeTime(item.created_at)}</span>
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={() => setOpen(true)} className="btn-ghost flex-1 !px-2 !py-1.5 text-[11px]">
              Review
            </button>
            {item.platform === "youtube" && item.has_video && item.status !== "published" && (
              <button onClick={publish} disabled={publishing} className="btn-primary flex-1 !px-2 !py-1.5 text-[11px]">
                Publish
              </button>
            )}
          </div>
        </div>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/85 p-4 backdrop-blur" onClick={() => setOpen(false)}>
          <div
            className="max-h-[90vh] w-full max-w-3xl animate-fade-up overflow-y-auto rounded-2xl border border-white/10 bg-ink-850"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 border-b border-white/[0.06] px-5 py-3">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold text-mist-100">{item.title}</h3>
                <p className="mt-0.5 text-[10px] uppercase tracking-wide text-mist-500">
                  {item.platform} · {item.kind} · {item.status} {item.published_at ? `· published ${dateTime(item.published_at)}` : ""}
                </p>
              </div>
              <button onClick={() => setOpen(false)} className="rounded-lg p-1.5 text-mist-500 hover:bg-white/5">
                <Icon name="x" className="h-4 w-4" />
              </button>
            </div>
            <div className="grid gap-4 p-5 md:grid-cols-[minmax(0,300px)_1fr]">
              <div>
                {item.has_video && token ? (
                  <video controls className="w-full rounded-xl border border-white/10" src={assetUrl(item.asset_url, token)} />
                ) : item.thumb_url && token ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={assetUrl(item.thumb_url, token)} alt={item.title} className="w-full rounded-xl border border-white/10" />
                ) : (
                  <div className="grid aspect-[9/13] place-items-center rounded-xl border border-white/10 bg-ink-950 text-xs text-mist-600">
                    No rendered media yet
                  </div>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {item.has_video && (
                    <a href={`/api/proxy/api/content/${item.id}/asset?t=${encodeURIComponent(token)}`} download className="btn-ghost !py-1.5 text-[11px]">
                      <Icon name="download" className="h-3.5 w-3.5" /> Download
                    </a>
                  )}
                  {item.external_id && (
                    <a
                      href={item.platform === "youtube" ? `https://youtu.be/${item.external_id}` : "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-ghost !py-1.5 text-[11px]"
                    >
                      <Icon name="external" className="h-3.5 w-3.5" /> Open post
                    </a>
                  )}
                </div>
              </div>
              <div className="min-w-0 space-y-4">
                <div>
                  <p className="label">Hook</p>
                  <p className="text-xs leading-relaxed text-mist-300">{item.hook || "—"}</p>
                </div>
                <div>
                  <p className="label">Caption</p>
                  <p className="whitespace-pre-line text-xs leading-relaxed text-mist-300">{item.caption || "—"}</p>
                </div>
                <div>
                  <p className="label">Script</p>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg border border-white/[0.06] bg-ink-950/60 p-3 text-[11px] leading-relaxed text-mist-400">
                    {item.script || "—"}
                  </pre>
                </div>
                <div>
                  <p className="label">Hashtags</p>
                  <p className="text-[11px] text-accent-soft">{item.hashtags || "—"}</p>
                </div>
                {item.scheduled_for && (
                  <p className="text-[11px] text-violet">Scheduled {dateTime(item.scheduled_for)}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
