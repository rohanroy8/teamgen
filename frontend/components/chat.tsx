// ChatMain: header, messages, per-answer "Why this answer?", scoped input.
"use client";
import { useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/collapsible";
import { WhyCollapsible } from "@/components/ui/collapsible";
import { useBackend, type Project } from "@/lib/api";

export type Msg = {
  role: "user" | "assistant";
  text: string;
  used?: string[];
  rejected?: { decision: string; reason: string }[];
};

export function Chat({ project, username, msgs, setMsgs }: {
  project: Project | null; username: string;
  msgs: Msg[]; setMsgs: (updater: (m: Msg[]) => Msg[]) => void;
}) {
  const api = useBackend();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const scopeHint = project ? `saving to: project/${project.name} as @${username}` : `saving to: personal as @${username}`;

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const d = await api.post<{ answer: string; used_ids: string[]; trace: { writes: { decision: string; reason: string }[] } }>(
        "/chat",
        project
          ? { text, project_id: project.id, scope: "project" }
          : { text, scope: "personal" }
      );
      setMsgs((m) => [...m, {
        role: "assistant", text: d.answer, used: d.used_ids,
        rejected: (d.trace.writes ?? []).filter((w) => w.decision !== "insert_active" && w.decision !== "supersede")
      }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: `Error: ${String(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b p-3">
        <h1 className="text-base font-semibold">{project ? project.name : "Personal"}</h1>
        <Badge tone={project ? "project" : "personal"}>{project ? "project" : "personal"}</Badge>
        {project ? <span className="text-xs text-neutral-400">as @{username}</span> : null}
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {msgs.map((m, i) => (
          <div key={i} className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" ? <Avatar username="t" /> : null}
            <div className={`max-w-[80%] rounded-lg p-2.5 text-sm ${m.role === "user" ? "bg-neutral-900 text-white" : "bg-neutral-100"}`}>
              <p className="whitespace-pre-wrap">{m.text}</p>
              {m.role === "assistant" && (m.used?.length || m.rejected?.length) ? (
                <WhyCollapsible>
                  <p>Used: {m.used?.length ? m.used.join(", ") : "none"}</p>
                  {(m.rejected ?? []).map((r, j) => (
                    <p key={j}>Not stored as truth: {r.decision} — {r.reason}</p>
                  ))}
                </WhyCollapsible>
              ) : null}
            </div>
          </div>
        ))}
        {busy ? <Skeleton className="h-10 w-2/3" /> : null}
      </div>
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            placeholder="Ask or tell anything…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          />
          <Button onClick={send}>Send</Button>
        </div>
        <p className="mt-1 text-xs text-neutral-400">{scopeHint}</p>
      </div>
    </main>
  );
}
