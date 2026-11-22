"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const TOKEN_KEY = "nova.token";
const BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/proxy";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

/** Turn FastAPI error payloads (string, or a validation-error array) into
 * text a person can read. Rendering the array directly showed "[object Object]". */
function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const lines = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        const entry = item as { msg?: unknown; loc?: unknown };
        const message = typeof entry.msg === "string" ? entry.msg : "";
        if (!message) return "";
        const field = Array.isArray(entry.loc)
          ? entry.loc.filter((part) => part !== "body").join(".")
          : "";
        return field ? `${field}: ${message}` : message;
      })
      .filter(Boolean);
    if (lines.length) return lines.join("; ");
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
    return JSON.stringify(detail);
  }
  return "";
}

export async function api<T>(
  path: string,
  options: RequestInit & { raw?: boolean } = {}
): Promise<T> {
  const token = getToken();
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isForm ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((options.headers as Record<string, string>) || {}),
  };
  const method = (options.method || "GET").toUpperCase();
  let response: Response | null = null;
  let networkError: unknown = null;
  const attempts = method === "GET" ? 3 : 1;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      response = await fetch(`${BASE}${path}`, { ...options, headers, cache: "no-store" });
      break;
    } catch (error) {
      networkError = error;
      if (attempt + 1 >= attempts) break;
      // Dev proxies can reset a keep-alive socket while the backend is rendering.
      await new Promise((resolve) => setTimeout(resolve, 350 * (attempt + 1)));
    }
  }
  if (!response) {
    throw new ApiError(0, networkError instanceof Error ? `Network error: ${networkError.message}` : "Network error");
  }

  if (response.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.dispatchEvent(new Event("nova:unauth"));
    throw new ApiError(401, "Session expired — sign in again.");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = describeDetail(payload.detail) || JSON.stringify(payload);
    } catch {
      /* keep status text */
    }
    throw new ApiError(response.status, detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const put = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

interface ApiState<T> {
  data: T | null;
  error: string;
  loading: boolean;
  refresh: () => void;
  setData: (value: T) => void;
}

/** Minimal fetch hook: abortable, refetchable, optional polling. */
export function useApi<T>(path: string | null, options: { pollMs?: number } = {}): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    api<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!cancelled && mounted.current) {
          setData(value);
          setError("");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Request failed");
      })
      .finally(() => {
        if (!cancelled && mounted.current) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [path, tick]);

  useEffect(() => {
    if (!options.pollMs || !path) return;
    const interval = window.setInterval(() => setTick((value) => value + 1), options.pollMs);
    return () => window.clearInterval(interval);
  }, [options.pollMs, path]);

  const refresh = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, refresh, setData: (value: T) => setData(value) };
}

/** Live task events via SSE (the backend also supports WebSockets). */
export function useEventStream(onEvent: (event: { type: string; task_id?: string; message?: string; data?: Record<string, unknown> }) => void) {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    let source: EventSource | null = null;
    let retry: number | undefined;
    let closed = false;

    const connect = () => {
      source = new EventSource(`${BASE}/api/system/events?t=${encodeURIComponent(token)}`);
      source.onopen = () => setConnected(true);
      source.onmessage = (message) => {
        try {
          handler.current(JSON.parse(message.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        if (!closed) retry = window.setTimeout(connect, 5000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      source?.close();
    };
  }, []);

  return connected;
}

/** Short-lived signed token used for <video>/<img>/download URLs. */
export function useAssetToken(): string {
  const [token, setToken] = useState("");
  useEffect(() => {
    api<{ token: string }>("/api/system/asset-token")
      .then((value) => setToken(value.token))
      .catch(() => setToken(""));
  }, []);
  return token;
}

export function assetUrl(path: string, token: string): string {
  if (!path) return "";
  const separator = path.includes("?") ? "&" : "?";
  return `${BASE}${path}${separator}t=${encodeURIComponent(token)}`;
}
