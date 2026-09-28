"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, errorMessage, type ChatTurn } from "@/lib/api";

const SUGGESTIONS = [
  "What's running low?",
  "What do I need to prepare for next month?",
  "How many TB patients are in treatment?",
  "Any batches expiring soon?",
];

interface Message {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
  error?: boolean;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    // Earlier turns give the model context for follow-ups; failed turns are left out.
    const history: ChatTurn[] = messages
      .filter((m) => !m.error)
      .map(({ role, content }) => ({ role, content }));
    setMessages((prev) => [...prev, { role: "user", content: message }]);
    setInput("");
    setSending(true);
    try {
      const r = await api.chat(message, history);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: r.response, tools: r.tools_used },
      ]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: errorMessage(e), error: true },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="mx-auto flex h-[calc(100dvh-4rem)] max-w-3xl flex-col px-6 pt-6 pb-4">
      <h1 className="text-xl font-semibold mb-4">Ask MedStock AI</h1>

      <div className="flex-1 overflow-y-auto rounded-xl border p-4 flex flex-col gap-4">
        {messages.length === 0 && (
          <p className="m-auto text-sm text-muted-foreground text-center max-w-sm">
            Ask about stock levels, forecasts, patients on treatment, expiring
            batches or purchase orders.
          </p>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-blue-600 px-4 py-2 text-sm text-white">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={i} className="flex flex-col items-start gap-1.5">
              <div
                className={`max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm px-4 py-2 text-sm ${
                  m.error
                    ? "bg-destructive/10 text-destructive"
                    : "bg-muted text-foreground"
                }`}
              >
                {m.content}
              </div>
              {m.tools && m.tools.length > 0 && (
                <div className="flex flex-wrap gap-1 pl-1">
                  {m.tools.map((t) => (
                    <Badge key={t} variant="outline" className="font-mono text-[11px]">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          )
        )}

        {sending && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm bg-muted px-4 py-2 text-sm text-muted-foreground animate-pulse">
              Thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            disabled={sending}
            onClick={() => send(s)}
            className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={2000}
          placeholder="Ask about stock, forecasts, patients, orders…"
          className="h-9 flex-1 rounded-lg border bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <Button type="submit" disabled={sending || !input.trim()}>
          Send
        </Button>
      </form>
    </main>
  );
}
