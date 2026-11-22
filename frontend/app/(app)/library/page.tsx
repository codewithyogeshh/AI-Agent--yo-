"use client";

import { useState } from "react";
import { ContentCard } from "@/components/ContentCard";
import { Icon } from "@/components/icons";
import { EmptyState, Panel, Skeleton, Tabs } from "@/components/ui";
import { assetUrl, useApi, useAssetToken } from "@/lib/api";
import { bytes, relativeTime } from "@/lib/format";
import type { ContentItem } from "@/lib/types";

interface Asset {
  id: string;
  name: string;
  path: string;
  mime: string;
  size: number;
  kind: string;
  created_at: string | null;
}

export default function LibraryPage() {
  const library = useApi<{ items: ContentItem[]; assets: Asset[] }>("/api/content/library", { pollMs: 30000 });
  const [filter, setFilter] = useState<"all" | "youtube" | "instagram" | "published">("all");
  const token = useAssetToken();

  const items = (library.data?.items ?? []).filter((item) => {
    if (filter === "all") return true;
    if (filter === "published") return item.status === "published";
    return item.platform === filter;
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Video library</h2>
          <p className="text-xs text-mist-500">Every rendered package, script and asset NOVA produced.</p>
        </div>
        <Tabs
          tabs={[
            { id: "all", label: "All" },
            { id: "youtube", label: "YouTube" },
            { id: "instagram", label: "Instagram" },
            { id: "published", label: "Published" },
          ]}
          value={filter}
          onChange={(value) => setFilter(value)}
        />
      </div>

      <Panel>
        {library.loading && !library.data ? (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="aspect-[9/13] w-full" />)}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            title="Library is empty"
            description="Produce content from the studio or ask NOVA for a video. Rendered files and their metadata appear here."
          />
        ) : (
          <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
            {items.map((item) => <ContentCard key={item.id} item={item} onChange={library.refresh} />)}
          </div>
        )}
      </Panel>

      <Panel title="Workspace assets" subtitle="Files written by tools, reports and uploads">
        {(library.data?.assets ?? []).length === 0 ? (
          <EmptyState title="No assets recorded" description="Generated reports, scripts and uploads are tracked here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-[10px] uppercase tracking-[0.12em] text-mist-600">
                <tr className="border-b border-white/[0.05]">
                  <th className="px-5 py-2.5 font-medium">Name</th>
                  <th className="px-3 py-2.5 font-medium">Kind</th>
                  <th className="px-3 py-2.5 font-medium">Size</th>
                  <th className="px-3 py-2.5 font-medium">Added</th>
                  <th className="px-5 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {(library.data?.assets ?? []).slice(0, 100).map((asset) => (
                  <tr key={asset.id} className="border-b border-white/[0.03] hover:bg-white/[0.015]">
                    <td className="max-w-[280px] truncate px-5 py-2.5 text-mist-200">{asset.name}</td>
                    <td className="px-3 py-2.5 text-mist-500">{asset.kind}</td>
                    <td className="px-3 py-2.5 text-mist-500">{bytes(asset.size)}</td>
                    <td className="px-3 py-2.5 text-mist-500">{relativeTime(asset.created_at)}</td>
                    <td className="px-5 py-2.5 text-right">
                      {token && (
                        <a
                          href={assetUrl(`/api/files/artifact?path=${encodeURIComponent(asset.path)}`, token)}
                          className="inline-flex items-center gap-1 text-accent-soft hover:underline"
                        >
                          <Icon name="download" className="h-3 w-3" /> open
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
