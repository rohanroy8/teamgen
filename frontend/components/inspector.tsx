// Inspector: Tabs (Memories | Conflicts | Digest | Catch-me-up) + history Timeline + revert + time-travel.
"use client";
import { useEffect, useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { Tabs } from "@/components/ui/tabs";
import { useBackend, type ConflictRow, type MemoryRow, type Project } from "@/lib/api";

type HistNode = {
  id: string; object: string; status: string; author: string;
  quote: string | null; valid_from: string; valid_to: string | null; recorded_at: string;
};

export function Inspector({ project }: { project: Project | null }) {
  const api = useBackend();
  const [mems, setMems] = useState<MemoryRow[]>([]);
  const [conflicts, setConflicts] = useState<ConflictRow[]>([]);
  const [digest, setDigest] = useState<Record<string, number>>({});
  const [brief, setBrief] = useState("");
  const [hist, setHist] = useState<{ chain: HistNode[] } | null>(null);
  const [asOf, setAsOf] = useState("");
  const [notice, setNotice] = useState("");

  const scopeParams = project ? { project_id: project.id, scope: "project" } : { scope: "personal" };
  const qs = new URLSearchParams(scopeParams as Record<string, string>).toString();

  async function refresh() {
    if (!api.token) return;
    try {
      const m = await api.get<{ memories: MemoryRow[] }>(`/memories?${qs}&limit=50`);
      setMems(m.memories);
    } catch { /* ignore */ }
    if (project) {
      try {
        const c = await api.get<{ conflicts: ConflictRow[] }>(`/conflicts?project_id=${project.id}`);
        setConflicts(c.conflicts);
        const d = await api.get<{ counts: Record<string, number> }>(`/digest?project_id=${project.id}&days=7`);
        setDigest(d.counts);
        const o = await api.get<{ brief: string }>(`/onboard?project_id=${project.id}`);
        setBrief(o.brief);
      } catch { /* ignore */ }
    } else {
      setConflicts([]); setDigest({}); setBrief("");
    }
  }
  useEffect(() => { refresh(); }, [api.token, project?.id]);

  async function openHistory(id: string) {
    const h = await api.get<{ chain: HistNode[] }>(`/memories/${id}/history`);
    setHist(h);
  }

  async function revert(id: string) {
    try {
      await api.post(`/memories/${id}/revert`, {});
      setNotice("reverted — prior fact restored");
      setHist(null);
      refresh();
    } catch (e) {
      setNotice(String(e));
    }
  }

  async function timeTravel() {
    if (!asOf) return;
    try {
      const d = project
        ? await api.get<{ facts: MemoryRow[] }>(`/memories/at?date=${asOf}&project_id=${project.id}`)
        : await api.get<{ facts: MemoryRow[] }>(`/memories/at?date=${asOf}`);
      setMems(d.facts);
      setNotice(`showing truth as of ${asOf}`);
    } catch (e) {
      setNotice(String(e));
    }
  }

  async function decideConflict(id: string, mode: string) {
    try {
      await api.post(`/conflicts/${id}/resolve`, { mode });
      setNotice(`conflict ${mode === "accept_both" ? "accepted both" : "resolved"}`);
      refresh();
    } catch (e) {
      setNotice(String(e));
    }
  }

  async function decideProposal(id: string, approve: boolean) {
    try {
      await api.post(`/proposals/${id}/${approve ? "approve" : "reject"}`, {});
      setNotice(approve ? "proposal approved" : "proposal rejected");
      refresh();
    } catch (e) {
      setNotice(String(e));
    }
  }

  const openConflicts = conflicts.filter((c) => c.status === "open");

  return (
    <aside className="flex w-96 flex-col border-l">
      <Tabs
        defaultValue="memories"
        tabs={[
          {
            value: "memories", label: `Memories (${mems.length})`,
            content: (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <Input placeholder="as-of date (ISO)" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
                  <Button onClick={timeTravel}>Go</Button>
                  <Button onClick={refresh}>Live</Button>
                </div>
                {mems.map((m) => (
                  <div key={m.id} className="rounded-lg border p-2 text-sm">
                    <div className="flex items-center gap-1.5">
                      <Avatar username={m.author} />
                      <span className="font-medium">@{m.author}</span>
                      <Badge tone={m.status}>{m.status}</Badge>
                      <Badge tone={m.scope}>{m.scope}</Badge>
                    </div>
                    <p className="mt-1">{m.subject} {m.predicate} <strong>{m.object}</strong></p>
                    {m.quote ? <p className="mt-0.5 text-xs text-neutral-500">“{m.quote}”</p> : null}
                    <div className="mt-1.5 flex gap-2 text-xs">
                      <button className="underline" onClick={() => openHistory(m.id)}>History</button>
                      <button className="underline" onClick={() => revert(m.id)}>Revert</button>
                    </div>
                  </div>
                ))}
              </div>
            )
          },
          {
            value: "conflicts", label: `Conflicts (${openConflicts.length})`,
            content: (
              <div className="space-y-2">
                {conflicts.map((c) => (
                  <div key={c.id} className="rounded-lg border p-2 text-sm">
                    <Badge tone={c.status}>{c.status}</Badge>
                    <p className="mt-1">A: {c.memory_a ? `@${c.memory_a.author}: ${c.memory_a.object} (${c.memory_a.status})` : "?"}</p>
                    <p>B: {c.memory_b ? `@${c.memory_b.author}: ${c.memory_b.object} (${c.memory_b.status})` : "?"}</p>
                    {c.status === "open" ? (
                      <div className="mt-1.5 flex flex-wrap gap-2 text-xs">
                        <button className="underline" onClick={() => decideConflict(c.id, "accept_both")}>Accept both</button>
                        {c.memory_a ? <button className="underline" onClick={() => decideConflict(c.id, c.memory_a!.id)}>A wins</button> : null}
                        {c.memory_b ? <button className="underline" onClick={() => decideConflict(c.id, c.memory_b!.id)}>B wins</button> : null}
                        {c.memory_b?.status === "proposed" ? <button className="underline" onClick={() => decideProposal(c.memory_b!.id, true)}>Approve PR</button> : null}
                        {c.memory_b?.status === "proposed" ? <button className="underline" onClick={() => decideProposal(c.memory_b!.id, false)}>Reject PR</button> : null}
                      </div>
                    ) : null}
                  </div>
                ))}
                {conflicts.length === 0 ? <p className="text-sm text-neutral-400">No conflicts. {project ? "" : "Select a project."}</p> : null}
              </div>
            )
          },
          {
            value: "digest", label: "Digest",
            content: (
              <div className="text-sm">
                {Object.entries(digest).map(([k, v]) => <p key={k}>{k}: {v}</p>)}
                {Object.keys(digest).length === 0 ? <p className="text-neutral-400">No activity yet. {project ? "" : "Select a project."}</p> : null}
              </div>
            )
          },
          {
            value: "catchup", label: "Catch-me-up",
            content: <pre className="whitespace-pre-wrap text-sm">{brief || "Select a project."}</pre>
          }
        ]}
      />
      {notice ? <p className="border-t p-2 text-xs text-neutral-600">{notice}</p> : null}

      <Dialog open={hist !== null} onOpenChange={(o) => { if (!o) setHist(null); }} title="Memory history">
        <div className="space-y-2 text-sm">
          {(hist?.chain ?? []).map((n, i) => (
            <div key={n.id} className="flex gap-2">
              <div className="flex flex-col items-center">
                <div className="h-2 w-2 rounded-full bg-neutral-800" />
                {i < (hist?.chain.length ?? 1) - 1 ? <div className="w-px flex-1 bg-neutral-300" /> : null}
              </div>
              <div>
                <p><strong>{n.object}</strong> <Badge tone={n.status}>{n.status}</Badge></p>
                <p className="text-xs text-neutral-500">@{n.author} · {n.valid_from?.slice(0, 10)}{n.valid_to ? ` → ${n.valid_to.slice(0, 10)}` : ""}</p>
                {n.quote ? <p className="text-xs text-neutral-500">“{n.quote}”</p> : null}
              </div>
            </div>
          ))}
        </div>
      </Dialog>
    </aside>
  );
}
