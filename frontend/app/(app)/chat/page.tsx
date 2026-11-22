"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { Badge, Markdown, Spinner, toast } from "@/components/ui";
import { api, post, useApi } from "@/lib/api";
import { clockTime, shortId } from "@/lib/format";
import type { AiCapabilities, ChatMessage, Overview, Task } from "@/lib/types";

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: ArrayLike<{ 0: { transcript: string }; isFinal?: boolean }>; resultIndex: number }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};

const SUGGESTIONS = [
  "Research the latest AI agent frameworks and send me a brief",
  "Create a 45-second Short about why recursion matters",
  "Summarise my unread emails",
  "Remind me tomorrow at 9am to review NOVA's logs",
  "Show me today's completed tasks",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [lastTaskId, setLastTaskId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  const history = useApi<{ messages: ChatMessage[] }>("/api/chat/messages");
  const overview = useApi<Overview>("/api/system/overview", { pollMs: 20000 });
  const capabilities = useApi<{ ai: AiCapabilities }>("/api/system/capabilities");
  const activeTask = useApi<{ task: Task }>(lastTaskId ? `/api/tasks/${lastTaskId}` : null, { pollMs: 3000 });

  useEffect(() => {
    if (history.data) setMessages(history.data.messages);
  }, [history.data]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending, activeTask.data?.task.status]);

  const speak = useCallback(
    (text: string) => {
      if (!speakReplies || typeof window === "undefined" || !("speechSynthesis" in window)) return;
      const utterance = new SpeechSynthesisUtterance(text.replace(/[*#`_]/g, "").slice(0, 500));
      utterance.rate = 1.03;
      utterance.pitch = 1;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    },
    [speakReplies]
  );

  async function send(text: string) {
    const content = text.trim();
    if (!content || sending) return;
    setSending(true);
    setInput("");
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      task_id: null,
      source: "web",
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    try {
      const result = await post<{ reply: ChatMessage; task: Task }>("/api/chat/messages", { content });
      setMessages((current) => [...current, result.reply]);
      setLastTaskId(result.task.id);
      speak(result.reply.content);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Message failed";
      toast(message, "bad");
      setMessages((current) => [
        ...current,
        { id: `err-${Date.now()}`, role: "assistant", content: `That failed: ${message}`, task_id: null, source: "system", created_at: new Date().toISOString() },
      ]);
    } finally {
      setSending(false);
    }
  }

  function toggleRecording() {
    if (recording) {
      recognitionRef.current?.stop();
      setRecording(false);
      return;
    }
    const globalWindow = window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
    const Recognition = globalWindow.SpeechRecognition || globalWindow.webkitSpeechRecognition;
    if (!Recognition) {
      toast("This browser has no speech recognition. Chrome on Android/desktop supports it.", "bad");
      return;
    }
    const recognition = new Recognition();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result?.[0]?.transcript ?? "")
        .join(" ");
      setInput(transcript);
    };
    recognition.onerror = () => {
      setRecording(false);
      toast("Voice capture failed", "bad");
    };
    recognition.onend = () => setRecording(false);
    recognitionRef.current = recognition;
    recognition.start();
    setRecording(true);
  }

  const offline = capabilities.data?.ai.offline_mode;

  return (
    <div className="mx-auto flex h-[calc(100dvh-8.5rem)] max-w-3xl flex-col sm:h-[calc(100dvh-7rem)]">
      <div className="flex items-center justify-between pb-3">
        <div>
          <h2 className="text-sm font-semibold text-mist-100">NOVA</h2>
          <p className="text-[11px] text-mist-500">
            {offline ? "Offline planner · tools active" : `${capabilities.data?.ai.provider} · ${capabilities.data?.ai.model}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSpeakReplies((value) => !value)}
            className={`chip ${speakReplies ? "border-accent/25 bg-accent/5 text-accent-soft" : "border-white/10 text-mist-500"}`}
            title="Speak replies aloud"
          >
            <Icon name={speakReplies ? "play" : "mic"} className="h-3 w-3" />
            voice {speakReplies ? "on" : "off"}
          </button>
          <span className="chip border-white/10 text-[10px] text-mist-500">
            {overview.data ? `${overview.data.stats.active} active` : "—"}
          </span>
        </div>
      </div>

      <div className="panel flex-1 overflow-y-auto p-4 sm:p-5">
        {messages.length === 0 && !history.loading && (
          <div className="flex h-full flex-col justify-center">
            <div className="mx-auto max-w-md text-center">
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl border border-accent/20 bg-accent/5 text-accent">
                <Icon name="spark" className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-semibold text-mist-100">Assign work in plain language</h3>
              <p className="mt-1 text-xs leading-relaxed text-mist-500">
                NOVA plans the task, picks tools, asks for approval when needed, then reports what actually happened.
              </p>
              <div className="mt-5 grid gap-2 text-left">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => send(suggestion)}
                    className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-left text-[12px] text-mist-300 transition hover:border-accent/30 hover:bg-accent/[0.06]"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="space-y-4">
          {messages.map((message) => (
            <div key={message.id} className={`flex gap-2.5 ${message.role === "user" ? "justify-end" : ""}`}>
              {message.role !== "user" && (
                <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-accent/20 bg-accent/5 text-accent">
                  <Icon name="spark" className="h-3.5 w-3.5" />
                </span>
              )}
              <div className={`max-w-[85%] ${message.role === "user" ? "rounded-2xl rounded-br-md bg-accent/10 px-4 py-2.5 text-[13px] text-mist-100" : "flex-1"}`}>
                {message.role === "user" ? (
                  <p className="whitespace-pre-line">{message.content}</p>
                ) : (
                  <Markdown content={message.content} />
                )}
                <div className="mt-1 flex items-center gap-2 text-[9px] text-mist-600">
                  <span>{clockTime(message.created_at)}</span>
                  {message.task_id && (
                    <Link href={`/tasks/${message.task_id}`} className="font-mono text-accent-soft/80 hover:underline">
                      {shortId(message.task_id)}
                    </Link>
                  )}
                </div>
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex items-center gap-2 text-xs text-mist-500">
              <Spinner className="h-3.5 w-3.5" /> Planning…
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {activeTask.data?.task && (
        <Link
          href={`/tasks/${activeTask.data.task.id}`}
          className="mt-2 flex items-center gap-3 rounded-xl border border-white/[0.07] bg-ink-850/80 px-3.5 py-2.5 transition hover:border-accent/25"
        >
          <Badge status={activeTask.data.task.status} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[11px] text-mist-200">{activeTask.data.task.title}</p>
            <p className="truncate text-[10px] text-mist-600">{activeTask.data.task.current_step || activeTask.data.task.status}</p>
          </div>
          <span className="text-[10px] text-mist-500">{activeTask.data.task.progress}%</span>
          <Icon name="arrow" className="h-3.5 w-3.5 text-mist-500" />
        </Link>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="mt-2 flex items-end gap-2 rounded-2xl border border-white/[0.08] bg-ink-850/90 p-2"
      >
        <button
          type="button"
          onClick={toggleRecording}
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl border transition ${
            recording ? "border-bad/40 bg-bad/15 text-bad" : "border-white/10 text-mist-400 hover:text-mist-100"
          }`}
          title="Voice input"
        >
          <Icon name="mic" className="h-4 w-4" />
        </button>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send(input);
            }
          }}
          rows={1}
          placeholder={recording ? "Listening…" : "Tell NOVA what to do…"}
          className="max-h-32 min-h-[36px] flex-1 resize-none bg-transparent px-1 py-2 text-sm text-mist-100 placeholder:text-mist-500 focus:outline-none"
        />
        <button type="submit" disabled={sending || !input.trim()} className="btn-primary h-9 !px-3" aria-label="Send">
          <Icon name="send" className="h-4 w-4" />
        </button>
      </form>
      <p className="mt-1.5 px-1 text-[10px] leading-relaxed text-mist-600">
        Voice capture uses your browser&apos;s speech engine. On-device only; nothing is uploaded for transcription.
      </p>
    </div>
  );
}
