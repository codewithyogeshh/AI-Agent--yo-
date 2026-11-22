"use client";

import { useEffect, useId, useState } from "react";
import { statusClass, statusLabel } from "@/lib/format";

export function Badge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`chip ${statusClass(status)}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label ?? statusLabel(status)}
    </span>
  );
}

export function Panel({
  children,
  className = "",
  title,
  subtitle,
  action,
}: {
  children?: React.ReactNode;
  className?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-white/[0.05] px-5 py-4">
          <div>
            {title && <h2 className="text-[13px] font-semibold tracking-wide text-mist-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-mist-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
  icon,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "accent" | "good" | "warn" | "bad";
  icon?: React.ReactNode;
}) {
  const tones = {
    default: "text-mist-100",
    accent: "text-accent-soft",
    good: "text-good",
    warn: "text-warn",
    bad: "text-bad",
  } as const;
  return (
    <div className="panel panel-hover px-5 py-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-mist-500">{label}</span>
        {icon && <span className="text-mist-500">{icon}</span>}
      </div>
      <div className={`mt-2 text-2xl font-semibold tracking-tight ${tones[tone]}`}>{value}</div>
      {hint && <p className="mt-1 text-[11px] text-mist-500">{hint}</p>}
    </div>
  );
}

export function Progress({ value, tone = "accent" }: { value: number; tone?: "accent" | "good" | "bad" | "warn" }) {
  const colors = { accent: "bg-accent", good: "bg-good", bad: "bg-bad", warn: "bg-warn" } as const;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <div
        className={`h-full rounded-full transition-all duration-500 ${colors[tone]}`}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="grid h-11 w-11 place-items-center rounded-2xl border border-white/[0.07] bg-white/[0.02] text-mist-500">
        {icon ?? (
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M12 3v18M3 12h18" strokeLinecap="round" />
          </svg>
        )}
      </div>
      <div>
        <p className="text-sm font-medium text-mist-200">{title}</p>
        {description && <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-mist-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-32" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    if (open) document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink-950/75 p-4 backdrop-blur-sm sm:items-center">
      <div className={`w-full ${width} animate-fade-up rounded-2xl border border-white/10 bg-ink-850 shadow-2xl`}>
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3.5">
          <h3 className="text-sm font-semibold text-mist-100">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1.5 text-mist-500 hover:bg-white/5 hover:text-mist-200" aria-label="Close">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-white/[0.06] px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  description?: string;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <div>
        <label htmlFor={id} className="text-[13px] font-medium text-mist-200">
          {label}
        </label>
        {description && <p className="mt-0.5 max-w-md text-xs leading-relaxed text-mist-500">{description}</p>}
      </div>
      <button
        id={id}
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition ${checked ? "bg-accent" : "bg-white/15"}`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-ink-950 transition ${checked ? "left-[18px]" : "left-0.5"}`}
        />
      </button>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-xl border border-white/[0.07] bg-ink-900/60 p-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
            value === tab.id ? "bg-white/[0.08] text-mist-100" : "text-mist-500 hover:text-mist-200"
          }`}
        >
          {tab.label}
          {tab.count !== undefined && <span className="ml-1.5 text-[10px] text-mist-500">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ markdown
function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inline(text: string): string {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

/** Small, dependency-free markdown renderer for agent output. */
export function Markdown({ content }: { content: string }) {
  const blocks: string[] = [];
  const lines = (content || "").split("\n");
  let list: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let code: string[] | null = null;

  const flushList = () => {
    if (list.length && listType) {
      blocks.push(`<${listType}>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</${listType}>`);
    }
    list = [];
    listType = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("```")) {
      if (code) {
        blocks.push(`<pre class="overflow-x-auto rounded-lg bg-ink-950/80 p-3 text-xs"><code>${escapeHtml(code.join("\n"))}</code></pre>`);
        code = null;
      } else {
        flushList();
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(raw);
      continue;
    }
    if (!line.trim()) {
      flushList();
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushList();
      const level = Math.min(heading[1].length + 1, 4);
      blocks.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      if (listType !== "ul") flushList();
      listType = "ul";
      list.push(bullet[1]);
      continue;
    }
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (numbered) {
      if (listType !== "ol") flushList();
      listType = "ol";
      list.push(numbered[1]);
      continue;
    }
    flushList();
    blocks.push(`<p>${inline(line)}</p>`);
  }
  flushList();
  if (code) blocks.push(`<pre class="overflow-x-auto rounded-lg bg-ink-950/80 p-3 text-xs"><code>${escapeHtml(code.join("\n"))}</code></pre>`);

  return <div className="prose-nova" dangerouslySetInnerHTML={{ __html: blocks.join("") }} />;
}

// ------------------------------------------------------------------ toasts
export function toast(message: string, tone: "info" | "good" | "bad" = "info") {
  window.dispatchEvent(new CustomEvent("nova:toast", { detail: { message, tone } }));
}

export function Toaster() {
  const [items, setItems] = useState<{ id: number; message: string; tone: string }[]>([]);
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ message: string; tone: string }>).detail;
      const id = Date.now() + Math.random();
      setItems((current) => [...current, { id, ...detail }]);
      window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 4200);
    };
    window.addEventListener("nova:toast", handler);
    return () => window.removeEventListener("nova:toast", handler);
  }, []);

  return (
    <div className="pointer-events-none fixed bottom-20 left-1/2 z-[60] flex w-full max-w-sm -translate-x-1/2 flex-col gap-2 px-4 sm:bottom-6 sm:left-auto sm:right-6 sm:translate-x-0">
      {items.map((item) => (
        <div
          key={item.id}
          className={`animate-fade-up rounded-xl border px-4 py-2.5 text-xs shadow-xl backdrop-blur ${
            item.tone === "bad"
              ? "border-bad/30 bg-bad/15 text-bad"
              : item.tone === "good"
                ? "border-good/30 bg-good/15 text-good"
                : "border-white/10 bg-ink-800/95 text-mist-200"
          }`}
        >
          {item.message}
        </div>
      ))}
    </div>
  );
}
