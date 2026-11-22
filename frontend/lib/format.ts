import type { TaskStatus } from "./types";

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.round(diff / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function clockTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function bytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

const STATUS_STYLE: Record<string, string> = {
  completed: "border-good/30 bg-good/10 text-good",
  running: "border-accent/40 bg-accent/10 text-accent-soft",
  planning: "border-accent/30 bg-accent/5 text-accent-soft",
  queued: "border-violet/30 bg-violet/10 text-violet",
  pending: "border-white/15 bg-white/5 text-mist-300",
  waiting_approval: "border-warn/35 bg-warn/10 text-warn",
  paused: "border-white/15 bg-white/5 text-mist-300",
  scheduled: "border-violet/25 bg-violet/5 text-violet",
  failed: "border-bad/35 bg-bad/10 text-bad",
  cancelled: "border-white/10 bg-white/5 text-mist-500 line-through",
  draft: "border-white/15 bg-white/5 text-mist-300",
  rendered: "border-accent/30 bg-accent/5 text-accent-soft",
  published: "border-good/30 bg-good/10 text-good",
  connected: "border-good/30 bg-good/10 text-good",
  needs_auth: "border-warn/30 bg-warn/10 text-warn",
  not_configured: "border-white/12 bg-white/5 text-mist-400",
  error: "border-bad/35 bg-bad/10 text-bad",
  info: "border-accent/25 bg-accent/5 text-accent-soft",
  warning: "border-warn/30 bg-warn/10 text-warn",
  success: "border-good/30 bg-good/10 text-good",
};

export function statusClass(status: string): string {
  return STATUS_STYLE[status] ?? "border-white/12 bg-white/5 text-mist-300";
}

export function statusLabel(status: TaskStatus | string): string {
  return String(status).replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 12 ? id.slice(0, 11) : id;
}

export function isActive(status: TaskStatus | string): boolean {
  return ["pending", "planning", "queued", "running", "waiting_approval"].includes(status);
}

export function toLocalInput(value?: string | null): string {
  const date = value ? new Date(value.endsWith("Z") ? value : `${value}Z`) : new Date();
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16);
}
