"use client";

import Link from "next/link";
import { useState } from "react";
import { post } from "@/lib/api";
import { relativeTime, shortId } from "@/lib/format";
import type { Approval } from "@/lib/types";
import { Icon } from "./icons";
import { Panel, Spinner, toast } from "./ui";

export function ApprovalCard({ approval, onChange }: { approval: Approval; onChange?: () => void }) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [note, setNote] = useState("");

  async function decide(approve: boolean) {
    setBusy(approve ? "approve" : "reject");
    try {
      await post(`/api/approvals/${approval.id}/decide`, { approve, note });
      toast(approve ? "Approved — task re-queued" : "Rejected — task cancelled", approve ? "good" : "bad");
      onChange?.();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Decision failed", "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel className="overflow-hidden">
      <div className="border-b border-white/[0.05] px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`chip ${approval.risk === "high" ? "border-bad/30 bg-bad/10 text-bad" : "border-warn/30 bg-warn/10 text-warn"}`}>
            {approval.risk} risk
          </span>
          <span className="code">{approval.tool}</span>
          <span className="text-[10px] text-mist-600">{relativeTime(approval.created_at)}</span>
        </div>
        <h3 className="mt-2 text-sm font-medium text-mist-100">{approval.action || approval.tool}</h3>
        <p className="mt-1 text-xs leading-relaxed text-mist-400">{approval.explanation}</p>
        {approval.task_id && (
          <Link href={`/tasks/${approval.task_id}`} className="mt-2 inline-flex items-center gap-1 text-[11px] text-accent-soft hover:underline">
            Task {shortId(approval.task_id)} · {approval.task_title || "open"}
            <Icon name="arrow" className="h-3 w-3" />
          </Link>
        )}
      </div>

      <div className="px-5 py-3">
        <p className="label">Payload</p>
        <pre className="max-h-44 overflow-auto rounded-lg border border-white/[0.06] bg-ink-950/70 p-3 font-mono text-[11px] leading-relaxed text-mist-300">
          {JSON.stringify(approval.payload, null, 2)}
        </pre>
        <input
          className="input mt-3"
          placeholder="Optional note for the audit log"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>

      <div className="flex gap-2 border-t border-white/[0.05] px-5 py-3">
        <button onClick={() => decide(true)} disabled={busy !== null} className="btn-primary flex-1">
          {busy === "approve" ? <Spinner /> : <Icon name="check" className="h-4 w-4" />}
          Approve &amp; run
        </button>
        <button onClick={() => decide(false)} disabled={busy !== null} className="btn-danger flex-1">
          {busy === "reject" ? <Spinner /> : <Icon name="x" className="h-4 w-4" />}
          Reject
        </button>
      </div>
    </Panel>
  );
}
