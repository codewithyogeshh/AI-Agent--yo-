"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, EmptyState, Panel, Skeleton, toast } from "@/components/ui";
import { api, post, useApi } from "@/lib/api";
import type { Integration, IntegrationPayload } from "@/lib/types";

interface ManagedQuota {
  available: boolean;
  used: number | null;
  limit: number | null;
  remaining: number | null;
  percent: number;
  resets_at: string;
  plan: string;
  unlimited: boolean;
  level: "ok" | "low" | "exhausted";
  error: string;
}

interface ManagedStatus {
  configured: boolean;
  platforms: { id: string; name: string; connected: boolean; handle: string; display_name: string }[];
  quota?: ManagedQuota;
  error: string;
}

export default function IntegrationsPage() {
  const integrations = useApi<IntegrationPayload>("/api/integrations", { pollMs: 60000 });
  const [busy, setBusy] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const managed = useApi<ManagedStatus>("/api/integrations/managed", { pollMs: 60000 });
  const [keyDraft, setKeyDraft] = useState("");
  const [editingKey, setEditingKey] = useState(false);

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const connected = search.get("connected");
    const failed = search.get("error");
    if (connected) toast(`${connected} connected`, "good");
    if (search.get("managed")) toast("Account linked — status refreshed below", "good");
    if (failed) toast(`${failed} connection failed — check the backend logs`, "bad");
  }, []);

  async function connect(provider: Integration) {
    if (provider.id === "whatsapp") {
      setExpanded(provider.id);
      return;
    }
    setBusy(provider.id);
    try {
      const result = await api<{ url: string }>(`/api/integrations/${provider.id}/authorize`);
      window.location.href = result.url;
    } catch (error) {
      toast(error instanceof Error ? error.message : "Authorisation unavailable", "bad");
      setExpanded(provider.id);
    } finally {
      setBusy("");
    }
  }

  async function saveManagedKey() {
    setBusy("managed-key");
    try {
      await post("/api/integrations/managed/key", { api_key: keyDraft.trim() });
      toast("Key saved — you can connect an account now", "good");
      setKeyDraft("");
      setEditingKey(false);
      managed.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not save the key", "bad");
    } finally {
      setBusy("");
    }
  }

  async function connectManaged(platform: string) {
    setBusy(`managed-${platform}`);
    try {
      const result = await post<{ url: string }>("/api/integrations/managed/connect", { platforms: [platform] });
      window.location.href = result.url;
    } catch (error) {
      toast(error instanceof Error ? error.message : "Connect failed", "bad");
    } finally {
      setBusy("");
    }
  }

  async function disconnectManaged(platform: string) {
    if (!window.confirm(`Disconnect ${platform}? NOVA loses access until you reconnect.`)) return;
    setBusy(`managed-${platform}`);
    try {
      await post("/api/integrations/managed/accounts/disconnect", { platform });
      toast("Disconnected", "good");
      managed.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Disconnect failed", "bad");
    } finally {
      setBusy("");
    }
  }

  async function test(provider: Integration) {
    setBusy(`test-${provider.id}`);
    try {
      const result = await post<{ ok: boolean; detail: string }>(`/api/integrations/${provider.id}/test`);
      toast(result.detail, result.ok ? "good" : "bad");
      integrations.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Test failed", "bad");
    } finally {
      setBusy("");
    }
  }

  async function disconnect(provider: Integration) {
    if (!window.confirm(`Disconnect ${provider.name}? Stored tokens will be deleted.`)) return;
    setBusy(provider.id);
    try {
      await post(`/api/integrations/${provider.id}/disconnect`);
      toast("Disconnected", "good");
      integrations.refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Disconnect failed", "bad");
    } finally {
      setBusy("");
    }
  }

  const ai = integrations.data?.ai;
  const media = integrations.data?.media;
  const whatsapp = integrations.data?.whatsapp;
  const quota = managed.data?.quota;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Integrations</h2>
        <p className="text-xs text-mist-500">
          Credentials live in backend environment variables. Status below reflects what is actually configured and authorised.
        </p>
      </div>

      <Panel title="One-click connect" subtitle="YouTube + Instagram without creating a Google Cloud or Meta developer app">
        <div className="space-y-3 px-5 py-4 text-[11px] leading-relaxed">
          {!managed.data?.configured || editingKey ? (
            <>
              <p className="text-mist-400">
                Paste one free Upload-Post API key. NOVA then opens their hosted connect page, so the only step left is
                approving the Google or Instagram consent screen for the account you want to use.
              </p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  type="password"
                  className="input flex-1"
                  value={keyDraft}
                  onChange={(event) => setKeyDraft(event.target.value)}
                  placeholder="up_..."
                  autoComplete="off"
                />
                <button
                  onClick={saveManagedKey}
                  disabled={busy !== "" || keyDraft.trim().length < 10}
                  className="btn-primary !py-1.5 text-[11px]"
                >
                  {busy === "managed-key" ? "Checking…" : "Save key"}
                </button>
                {editingKey && (
                  <button onClick={() => setEditingKey(false)} className="btn-ghost !py-1.5 text-[11px]">
                    Cancel
                  </button>
                )}
              </div>
              <p className="text-mist-600">
                Free plan: 2 connected accounts and 10 uploads per month. Create the key at{" "}
                <a href="https://app.upload-post.com" target="_blank" rel="noopener noreferrer" className="text-accent-soft">
                  app.upload-post.com
                </a>{" "}
                → API. It is validated, encrypted at rest and never shown again.
              </p>
            </>
          ) : (
            <>
              {quota?.available && (
                <div className="rounded-lg border border-white/[0.07] px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-mist-300">Monthly uploads</span>
                    <span className={quota.level === "exhausted" ? "text-bad" : quota.level === "low" ? "text-warn" : "text-mist-400"}>
                      {quota.unlimited ? `${quota.used} used · unlimited` : `${quota.used} / ${quota.limit} used`}
                      {quota.plan ? ` · ${quota.plan}` : ""}
                    </span>
                  </div>
                  {!quota.unlimited && (
                    <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/10">
                      <div
                        className={quota.level === "exhausted" ? "h-full bg-bad" : quota.level === "low" ? "h-full bg-warn" : "h-full bg-accent"}
                        style={{ width: `${quota.percent}%` }}
                      />
                    </div>
                  )}
                  {quota.level !== "ok" && (
                    <p className={quota.level === "exhausted" ? "mt-1.5 text-bad/80" : "mt-1.5 text-warn/80"}>
                      {quota.level === "exhausted"
                        ? "Allowance used up — new uploads will fail until it resets"
                        : `Only ${quota.remaining} upload${quota.remaining === 1 ? "" : "s"} left this month`}
                      {quota.resets_at ? ` · resets ${quota.resets_at}` : ""}
                    </p>
                  )}
                </div>
              )}
              {quota?.error && (
                <p className="text-[10px] text-mist-600">Upload usage unavailable: {quota.error}</p>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                {(managed.data?.platforms ?? []).map((platform) => (
                  <div
                    key={platform.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.07] px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="text-mist-200">{platform.name}</p>
                      <p className="truncate text-[10px] text-mist-600">
                        {platform.connected ? platform.handle || platform.display_name || "connected" : "not connected"}
                      </p>
                    </div>
                    {platform.connected ? (
                      <button
                        onClick={() => disconnectManaged(platform.id)}
                        disabled={busy !== ""}
                        className="btn-ghost !py-1 text-[10px]"
                      >
                        Disconnect
                      </button>
                    ) : (
                      <button
                        onClick={() => connectManaged(platform.id)}
                        disabled={busy !== ""}
                        className="btn-primary !py-1 text-[10px]"
                      >
                        {busy === `managed-${platform.id}` ? "Opening…" : "Connect"}
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {managed.data?.error && <p className="text-bad/80">{managed.data.error}</p>}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => managed.refresh()} className="btn-ghost !py-1 text-[10px]">
                  Refresh status
                </button>
                <button
                  onClick={() => {
                    setEditingKey(true);
                    setKeyDraft("");
                  }}
                  className="btn-ghost !py-1 text-[10px]"
                >
                  Change key
                </button>
              </div>
              <p className="text-mist-600">
                Linked through Upload-Post&apos;s verified apps, so no developer app is needed. YouTube uploads and
                Instagram Reels publish through this connection automatically; the direct API below is only used when no
                managed account is linked.
              </p>
            </>
          )}
        </div>
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        {integrations.loading && !integrations.data
          ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-44 w-full" />)
          : (integrations.data?.integrations ?? []).map((provider) => (
              <Panel key={provider.id} className="flex flex-col">
                <div className="flex items-start justify-between gap-3 border-b border-white/[0.05] px-5 py-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="truncate text-[13px] font-semibold text-mist-100">{provider.name}</h3>
                      <Badge status={provider.effective_status ?? provider.status} />
                    </div>
                    <p className="mt-0.5 text-[10px] uppercase tracking-wide text-mist-600">{provider.category}</p>
                  </div>
                  <Icon
                    name={provider.id === "google" ? "emails" : provider.id === "youtube" ? "youtube" : provider.id === "instagram" ? "instagram" : "chat"}
                    className="h-5 w-5 shrink-0 text-mist-500"
                  />
                </div>

                <div className="flex-1 px-5 py-3">
                  <ul className="space-y-1">
                    {provider.capabilities.map((capability) => (
                      <li key={capability} className="flex items-start gap-1.5 text-[11px] text-mist-400">
                        <Icon name="check" className="mt-0.5 h-3 w-3 shrink-0 text-mist-600" />
                        {capability}
                      </li>
                    ))}
                  </ul>
                  {provider.env.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1">
                      {provider.env.map((env) => (
                        <span key={env} className={`chip text-[9px] ${provider.env_configured ? "border-good/20 text-good" : "border-white/10 text-mist-500"}`}>
                          {env}
                        </span>
                      ))}
                    </div>
                  )}
                  {provider.last_error && <p className="mt-2 text-[10px] leading-relaxed text-bad/80">{provider.last_error}</p>}
                </div>

                <div className="flex flex-wrap gap-2 border-t border-white/[0.05] px-5 py-3">
                  {(provider.effective_status ?? provider.status) === "connected" ? (
                    provider.channel === "direct" ? (
                      <>
                        <button onClick={() => test(provider)} disabled={busy !== ""} className="btn-ghost !py-1.5 text-[11px]">
                          {busy === `test-${provider.id}` ? "Testing…" : "Test connection"}
                        </button>
                        <button onClick={() => disconnect(provider)} disabled={busy !== ""} className="btn-danger !py-1.5 text-[11px]">
                          Disconnect
                        </button>
                      </>
                    ) : (
                      <span className="text-[10px] leading-relaxed text-mist-500">
                        Connected via Upload-Post{provider.managed_handle ? ` · ${provider.managed_handle}` : ""} — NOVA
                        publishes through this connection.
                      </span>
                    )
                  ) : (
                    <button
                      onClick={() => connect(provider)}
                      disabled={busy !== ""}
                      className={(provider.effective_status ?? provider.status) === "not_configured" ? "btn-ghost !py-1.5 text-[11px]" : "btn-primary !py-1.5 text-[11px]"}
                    >
                      {(provider.effective_status ?? provider.status) === "needs_auth" ? "Connect account" : "Setup instructions"}
                    </button>
                  )}
                  <button onClick={() => setExpanded(expanded === provider.id ? null : provider.id)} className="btn-ghost !py-1.5 text-[11px]">
                    {expanded === provider.id ? "Hide steps" : "How to set up"}
                  </button>
                  <a href={provider.docs} target="_blank" rel="noopener noreferrer" className="ml-auto self-center text-[10px] text-mist-600 hover:text-accent-soft">
                    docs ↗
                  </a>
                </div>

                {expanded === provider.id && (
                  <div className="border-t border-white/[0.05] bg-ink-950/40 px-5 py-3">
                    <p className="label">Setup checklist</p>
                    <ol className="list-decimal space-y-1.5 pl-4 text-[11px] leading-relaxed text-mist-400">
                      {provider.setup.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ol>
                    <p className="mt-2 text-[10px] leading-relaxed text-mist-600">
                      Add values to <span className="code">backend/.env</span>, restart the backend, then reload this page.
                    </p>
                  </div>
                )}
              </Panel>
            ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="WhatsApp control channel" subtitle="Official Cloud API with signature validation">
          <div className="space-y-3 px-5 py-4 text-[11px] leading-relaxed">
            <div className="flex flex-wrap items-center gap-2">
              <Badge status={whatsapp?.configured ? "connected" : "not_configured"} label={whatsapp?.configured ? "sending enabled" : "not configured"} />
              <Badge status={whatsapp?.signature_enforced ? "connected" : "error"} label={whatsapp?.signature_enforced ? "signature enforced" : "signature NOT enforced"} />
            </div>
            <div>
              <p className="label">Webhook URL</p>
              <code className="block break-all rounded-lg border border-white/[0.07] bg-ink-950/60 px-3 py-2 font-mono text-[10px] text-mist-300">
                {whatsapp?.webhook_url || "Set PUBLIC_BASE_URL to see the public webhook URL"}
              </code>
            </div>
            <div>
              <p className="label">Authorised numbers</p>
              {(whatsapp?.allowed_numbers ?? []).length === 0 ? (
                <p className="text-warn">No numbers allowlisted — every inbound message is rejected.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {whatsapp?.allowed_numbers.map((number) => (
                    <span key={number} className="chip border-good/20 text-[10px] text-good">{number}</span>
                  ))}
                </div>
              )}
            </div>
            <ol className="list-decimal space-y-1 pl-4 text-mist-500">
              <li>Create a Meta app → add the WhatsApp product → get a test or production number.</li>
              <li>Set WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN.</li>
              <li>Point the callback URL at the webhook above; subscribe to <span className="code">messages</span>.</li>
              <li>Add your own number to WHATSAPP_ALLOWED_NUMBERS and save it on the Mobile page.</li>
            </ol>
            <p className="rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-mist-500">
              Voice notes are transcribed only when OPENAI_API_KEY or GEMINI_API_KEY is set; otherwise NOVA asks for text.
            </p>
          </div>
        </Panel>

        <div className="space-y-3">
          <Panel title="AI provider" subtitle="Planning, writing, summaries">
            <div className="px-5 py-4">
              <div className="flex items-center gap-2">
                <Badge status={ai?.configured ? "connected" : "not_configured"} label={ai?.configured ? `${ai?.provider}` : "offline planner"} />
                {ai?.model && <span className="code">{ai.model}</span>}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-mist-500">{ai?.note}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"].map((env) => (
                  <span key={env} className="chip border-white/10 text-[9px] text-mist-500">{env}</span>
                ))}
              </div>
            </div>
          </Panel>

          <Panel title="Media pipeline" subtitle="Rendering and voice">
            <ul className="divide-y divide-white/[0.05] text-[11px]">
              {[
                { label: "ffmpeg", ok: media?.ffmpeg, detail: media?.ffmpeg ? media.ffmpeg_binary : "not found" },
                { label: "Render font", ok: Boolean(media?.font), detail: media?.font ? "bundled Inter" : "missing" },
                { label: "Text to speech", ok: media?.tts, detail: media?.tts ? "configured" : "silent track" },
                { label: "AI images", ok: media?.ai_images, detail: media?.ai_images ? "configured" : "scene cards only" },
              ].map((row) => (
                <li key={row.label} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <span className="text-mist-300">{row.label}</span>
                  <span className={`text-[10px] ${row.ok ? "text-good" : "text-mist-500"}`}>{row.detail}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      <Panel title="Not connected?" subtitle="Nothing here is simulated">
        <div className="px-5 py-4">
          <EmptyState
            title="Interfaces are real, credentials are yours"
            description="Every integration above talks to the official API. Until you add credentials, NOVA reports “not configured” and keeps the workflow waiting rather than faking a result."
          />
        </div>
      </Panel>
    </div>
  );
}
