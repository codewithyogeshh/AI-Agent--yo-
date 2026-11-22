"use client";

import Link from "next/link";
import { useState } from "react";
import { ContentCard } from "@/components/ContentCard";
import { Icon } from "@/components/icons";
import { EmptyState, Panel, Skeleton, Stat, toast } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import type { ContentItem, IntegrationPayload } from "@/lib/types";

interface IgAnalytics {
  ok: boolean;
  detail: string;
  data: Record<string, string | number>;
  setup_required: string;
}

export default function InstagramPage() {
  const integrations = useApi<IntegrationPayload>("/api/integrations", { pollMs: 60000 });
  const analytics = useApi<IgAnalytics>("/api/publishing/instagram/analytics", { pollMs: 60000 });
  const content = useApi<{ items: ContentItem[] }>("/api/content?platform=instagram", { pollMs: 20000 });
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);

  const instagram = integrations.data?.integrations.find((item) => item.id === "instagram");
  const items = content.data?.items ?? [];

  async function produce(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setBusy(true);
    try {
      const result = await post<{ task: { id: string } }>("/api/content/generate", {
        topic,
        platform: "instagram",
        format: "vertical",
        duration: 45,
      });
      toast("Reel production queued", "good");
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
          <h2 className="text-lg font-semibold tracking-tight">Instagram Studio</h2>
          <p className="text-xs text-mist-500">Reels via the official Meta Graph API — publishing needs a public video URL.</p>
        </div>
        <span className={`chip ${instagram?.status === "connected" ? "border-good/25 bg-good/5 text-good" : "border-warn/25 bg-warn/5 text-warn"}`}>
          {instagram?.status === "connected" ? "account connected" : instagram?.status === "needs_auth" ? "authorise account" : "credentials missing"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Followers" value={analytics.data?.data?.followers_count ?? "—"} tone="accent" hint={analytics.data?.ok ? "live from Meta" : "not connected"} />
        <Stat label="Posts" value={analytics.data?.data?.media_count ?? "—"} hint="account total" />
        <Stat label="Reels ready" value={items.filter((item) => item.has_video).length} hint="rendered locally" />
        <Stat label="Published" value={items.filter((item) => item.status === "published").length} hint="through NOVA" />
      </div>

      {analytics.data && !analytics.data.ok && (
        <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/[0.02] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2.5">
            <Icon name="instagram" className="mt-0.5 h-4 w-4 shrink-0 text-violet" />
            <p className="text-xs leading-relaxed text-mist-400">{analytics.data?.detail || "Connect an Instagram Business account to publish and read insights."}</p>
          </div>
          <Link href="/integrations" className="btn-ghost shrink-0 !py-1.5 text-[11px]">Connection setup</Link>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Panel title="Produce a Reel" subtitle="Vertical 9:16 · captions burned in · cover image generated">
          <form onSubmit={produce} className="space-y-3 px-5 py-4">
            <div>
              <label className="label">Reel idea</label>
              <textarea
                className="input min-h-[80px] resize-y"
                placeholder="e.g. Three Java mistakes that slow down beginners"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
            </div>
            <div className="flex flex-wrap gap-2 text-[10px] text-mist-500">
              <span className="chip border-white/10">vertical reel</span>
              <span className="chip border-white/10">45 s</span>
              <span className="chip border-white/10">hashtag set</span>
            </div>
            <button type="submit" disabled={busy || !topic.trim()} className="btn-primary w-full">
              {busy ? "Queueing…" : "Produce Reel"}
            </button>
          </form>
        </Panel>

        <Panel title="Platform limits" subtitle="What the official API cannot do">
          <div className="space-y-3 px-5 py-4 text-[11px] leading-relaxed text-mist-400">
            <p>
              <span className="text-mist-200">Supported:</span> publishing Reels and single images for Business/Creator
              accounts linked to a Facebook Page, plus basic insights.
            </p>
            <p>
              <span className="text-mist-200">Not supported by the API:</span> Stories publishing, some carousel
              arrangements, direct messages, and scheduling without a public media URL.
            </p>
            <p>
              NOVA therefore renders the Reel locally, prepares caption + hashtags, and either publishes through the API
              when a <span className="code">PUBLIC_BASE_URL</span> is configured or hands you a ready-to-upload file.
            </p>
            <p className="rounded-lg border border-warn/20 bg-warn/[0.05] px-3 py-2 text-warn">
              Public media URLs are required by Meta. Without one, publishing is blocked — NOVA will say so instead of
              pretending it worked.
            </p>
          </div>
        </Panel>
      </div>

      <Panel title="Reels" subtitle="Drafts, renders and published posts">
        {content.loading && !content.data ? (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="aspect-[9/13] w-full" />)}
          </div>
        ) : items.length === 0 ? (
          <EmptyState title="No Reels yet" description="Start a production above. The rendered cover and script will appear here." />
        ) : (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-5">
            {items.map((item) => <ContentCard key={item.id} item={item} onChange={content.refresh} />)}
          </div>
        )}
      </Panel>
    </div>
  );
}
