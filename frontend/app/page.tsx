// Protected home: Sidebar | ChatMain | Inspector (ChatGPT-clone, projects as sidebar).
"use client";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { Chat, type Msg } from "@/components/chat";
import { Inspector } from "@/components/inspector";
import { useBackend } from "@/lib/api";
import type { Project } from "@/lib/api";

const SCOPE_KEY = (id: string | null) => `chat:${id ?? "personal"}`;

function loadStored(key: string): Msg[] {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Msg[]) : [];
  } catch {
    return [];
  }
}

export default function Home() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  // Chat state lives HERE (above the remounting Chat): switching projects can
  // never drop it. localStorage is a reload-backup, loaded lazily per scope.
  const [chats, setChats] = useState<Record<string, Msg[]>>({});
  const [hydrated, setHydrated] = useState(false);

  const api = useBackend();
  useEffect(() => {
    if (!api.token) return;
    api.get<{ projects: Project[] }>("/projects/mine").then(
      (d) => setProjects(d.projects),
      () => {}
    );
  }, [api.token]);

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  // One-time hydration of stored conversations (client-only).
  useEffect(() => {
    setChats((c) => {
      if (Object.keys(c).length) return c;
      const next: Record<string, Msg[]> = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k?.startsWith("chat:")) next[k] = loadStored(k);
      }
      return next;
    });
    setHydrated(true);
  }, []);

  const scopeKey = SCOPE_KEY(activeId);
  const msgs = chats[scopeKey] ?? [];
  function setMsgs(updater: (m: Msg[]) => Msg[]) {
    setChats((prev) => {
      const next = updater(prev[scopeKey] ?? []);
      try {
        localStorage.setItem(scopeKey, JSON.stringify(next.slice(-50)));
      } catch { /* blocked storage: in-memory still works */ }
      return { ...prev, [scopeKey]: next };
    });
  }

  const username =
    (session?.user as { username?: string } | undefined)?.username ??
    session?.user?.name ?? "user";
  const active = projects.find((p) => p.id === activeId) ?? null;

  if (status === "loading") return <main className="p-8 text-sm">Loading…</main>;
  if (!session) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar username={username} activeId={activeId} onSelect={setActiveId} />
      <Chat
        key={activeId ?? "personal"}
        project={active}
        username={username}
        msgs={hydrated ? msgs : []}
        setMsgs={setMsgs}
      />
      <Inspector project={active} />
    </div>
  );
}
