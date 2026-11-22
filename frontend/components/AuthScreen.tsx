"use client";

import { useEffect, useState } from "react";
import { api, post, setToken } from "@/lib/api";
import type { User } from "@/lib/types";
import { Spinner } from "./ui";

export default function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [registrationOpen, setRegistrationOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api<{ registration_open: boolean; provider: string }>("/api/auth/status")
      .then((status) => {
        setRegistrationOpen(status.registration_open);
        if (status.registration_open) setMode("register");
      })
      .catch(() => undefined)
      .finally(() => setChecking(false));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (mode === "register" && password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    try {
      const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
      const body = mode === "register" ? { email, password, name } : { email, password };
      const result = await post<{ token: string; user: User }>(path, body);
      setToken(result.token);
      onAuthenticated(result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-5 py-10">
      <div className="pointer-events-none absolute inset-0 grid-lines opacity-70" />
      <div className="relative w-full max-w-[400px]">
        <div className="mb-8 flex items-center gap-3">
          <NovaMark />
          <div>
            <h1 className="text-lg font-semibold tracking-[0.22em] text-mist-100">NOVA</h1>
            <p className="text-[11px] uppercase tracking-[0.18em] text-mist-500">Personal AI Operator</p>
          </div>
        </div>

        <div className="panel animate-fade-up p-6 shadow-glow">
          <h2 className="text-base font-semibold text-mist-100">
            {mode === "register" ? "Create your owner account" : "Sign in"}
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-mist-500">
            {mode === "register"
              ? "This is the single owner account for your NOVA instance. Use a strong password — it protects every connected account."
              : "Your session is a signed JWT. Nothing is stored in the browser beyond the token."}
          </p>

          <form onSubmit={submit} className="mt-5 space-y-3.5">
            {mode === "register" && (
              <div>
                <label className="label" htmlFor="name">
                  Name
                </label>
                <input id="name" className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" autoComplete="name" />
              </div>
            )}
            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                className="input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={10}
                className="input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={mode === "register" ? "At least 10 characters" : "••••••••••"}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
              />
            </div>
            {mode === "register" && (
              <div>
                <label className="label" htmlFor="confirm">
                  Confirm password
                </label>
                <input
                  id="confirm"
                  type="password"
                  required
                  className="input"
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  autoComplete="new-password"
                />
              </div>
            )}

            {error && <p className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs text-bad">{error}</p>}

            <button type="submit" disabled={busy || checking} className="btn-primary w-full">
              {busy ? <Spinner /> : null}
              {mode === "register" ? "Create account" : "Sign in"}
            </button>
          </form>

          {registrationOpen && (
            <button
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError("");
              }}
              className="mt-4 w-full text-center text-[11px] text-mist-500 hover:text-mist-300"
            >
              {mode === "login" ? "Set up a new owner account" : "Back to sign in"}
            </button>
          )}
        </div>

        <p className="mt-6 text-center text-[11px] leading-relaxed text-mist-600">
          NOVA runs locally by default. API keys live in backend environment variables and never reach the browser.
        </p>
      </div>
    </div>
  );
}

export function NovaMark({ size = 40 }: { size?: number }) {
  return (
    <div
      className="relative grid place-items-center rounded-2xl border border-accent/20 bg-ink-850"
      style={{ width: size, height: size }}
    >
      <div className="absolute inset-0 rounded-2xl bg-accent/[0.07]" />
      <svg viewBox="0 0 24 24" width={size * 0.55} height={size * 0.55} className="relative text-accent">
        <circle cx="12" cy="12" r="7.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeOpacity="0.55" />
        <circle cx="12" cy="12" r="2.4" fill="currentColor" />
        <path d="M12 1.4v4M12 18.6v4M1.4 12h4M18.6 12h4" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeOpacity="0.8" />
      </svg>
    </div>
  );
}
