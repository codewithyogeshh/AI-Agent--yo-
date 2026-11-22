"use client";

import Link from "next/link";
import { useState } from "react";
import { Icon } from "@/components/icons";
import { EmptyState, Modal, Panel, Skeleton, toast } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { EmailMessage, Task } from "@/lib/types";

interface EmailsResponse {
  connected: boolean;
  emails: EmailMessage[];
  query: string;
}

export default function EmailsPage() {
  const [query, setQuery] = useState("is:unread");
  const [applied, setApplied] = useState("is:unread");
  const [compose, setCompose] = useState(false);
  const inbox = useApi<EmailsResponse>(`/api/productivity/emails?query=${encodeURIComponent(applied)}&limit=15`);
  const [summarising, setSummarising] = useState(false);

  async function summarize() {
    setSummarising(true);
    try {
      const result = await post<{ task: Task }>("/api/tasks", {
        prompt: "Check my emails and summarize the important ones. Flag anything urgent or suspicious.",
      });
      toast("Inbox summary queued", "good");
      window.location.href = `/tasks/${result.task.id}`;
    } catch (error) {
      toast(error instanceof Error ? error.message : "Failed", "bad");
    } finally {
      setSummarising(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Emails</h2>
          <p className="text-xs text-mist-500">Read-only by default. Sending always needs your explicit action.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={summarize} disabled={summarising || !inbox.data?.connected} className="btn-ghost !py-1.5 text-[11px]">
            <Icon name="spark" className="h-3.5 w-3.5" /> Summarise
          </button>
          <button onClick={() => setCompose(true)} className="btn-primary !py-1.5 text-[11px]">
            <Icon name="send" className="h-3.5 w-3.5" /> Compose
          </button>
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setApplied(query);
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-mist-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Gmail search, e.g. is:unread newer_than:2d from:github"
            className="input pl-8 text-xs"
          />
        </div>
        <button type="submit" className="btn-ghost text-[11px]">Search</button>
      </form>

      {inbox.data && !inbox.data.connected && (
        <div className="flex flex-col gap-2 rounded-2xl border border-white/10 bg-white/[0.02] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-relaxed text-mist-400">
            Gmail is not connected. NOVA never shows placeholder mail — connect Google to read your inbox.
          </p>
          <Link href="/integrations" className="btn-ghost shrink-0 !py-1.5 text-[11px]">Connect Gmail</Link>
        </div>
      )}

      <Panel title={inbox.data?.connected ? `Results · ${inbox.data.query}` : "Inbox"} subtitle="Newest first">
        {inbox.loading && !inbox.data ? (
          <div className="space-y-2 p-4"><Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" /><Skeleton className="h-14 w-full" /></div>
        ) : inbox.error ? (
          <EmptyState title="Could not read mail" description={inbox.error} />
        ) : (inbox.data?.emails ?? []).length === 0 ? (
          <EmptyState
            title={inbox.data?.connected ? "No messages match" : "Not connected"}
            description={inbox.data?.connected ? "Try a different Gmail query." : "Connect Google to load your messages."}
            icon={<Icon name="emails" className="h-5 w-5" />}
          />
        ) : (
          <ul className="divide-y divide-white/[0.05]">
            {(inbox.data?.emails ?? []).map((email) => (
              <li key={email.id} className="px-5 py-3.5 transition hover:bg-white/[0.015]">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-[12px] font-medium text-mist-100">{email.subject}</p>
                    <p className="truncate text-[11px] text-mist-500">{email.from}</p>
                  </div>
                  <span className="shrink-0 text-[10px] text-mist-600">{email.date || relativeTime(null)}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-mist-500">{email.snippet}</p>
                <div className="mt-1.5 flex gap-1.5">
                  {(email.labels ?? []).slice(0, 4).map((label) => (
                    <span key={label} className="chip border-white/[0.07] text-[9px] text-mist-600">{label}</span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="How NOVA handles mail" subtitle="Permissions and safety">
        <ul className="space-y-2 px-5 py-4 text-[11px] leading-relaxed text-mist-400">
          <li className="flex gap-2"><Icon name="check" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-good" /> Reading and summarising runs on request only.</li>
          <li className="flex gap-2"><Icon name="shield" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" /> Agent-initiated sends create an approval request with the full draft.</li>
          <li className="flex gap-2"><Icon name="x" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" /> Email bodies are treated as untrusted data, never as instructions.</li>
        </ul>
      </Panel>

      <ComposeModal open={compose} onClose={() => setCompose(false)} connected={Boolean(inbox.data?.connected)} />
    </div>
  );
}

function ComposeModal({ open, onClose, connected }: { open: boolean; onClose: () => void; connected: boolean }) {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function send() {
    setBusy(true);
    try {
      await post("/api/productivity/emails/send", { to, subject, body });
      toast("Email sent", "good");
      setTo("");
      setSubject("");
      setBody("");
      setConfirming(false);
      onClose();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Send failed", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Compose email"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          {confirming ? (
            <button onClick={send} disabled={busy} className="btn-danger">
              {busy ? "Sending…" : "Confirm send"}
            </button>
          ) : (
            <button onClick={() => setConfirming(true)} disabled={!connected || !to || !subject} className="btn-primary">
              Review &amp; send
            </button>
          )}
        </>
      }
    >
      {!connected && (
        <p className="mb-3 rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2 text-[11px] text-warn">
          Gmail is not connected — sending is disabled until you authorise the account.
        </p>
      )}
      <div className="space-y-3">
        <div>
          <label className="label">To</label>
          <input className="input" type="email" value={to} onChange={(event) => setTo(event.target.value)} placeholder="name@example.com" />
        </div>
        <div>
          <label className="label">Subject</label>
          <input className="input" value={subject} onChange={(event) => setSubject(event.target.value)} />
        </div>
        <div>
          <label className="label">Message</label>
          <textarea className="input min-h-[140px]" value={body} onChange={(event) => setBody(event.target.value)} />
        </div>
        {confirming && (
          <p className="rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2 text-[11px] leading-relaxed text-warn">
            You are about to send this from your connected Gmail account. This is logged in the audit trail.
          </p>
        )}
      </div>
    </Modal>
  );
}
