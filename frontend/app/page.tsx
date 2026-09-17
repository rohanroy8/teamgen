// Protected home: Sidebar | ChatMain | Inspector (ChatGPT-clone, projects as sidebar).
"use client";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { Chat } from "@/components/chat";
import { Inspector } from "@/components/inspector";
import type { Project } from "@/lib/api";

export default function Home() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  const username =
    (session?.user as { username?: string } | undefined)?.username ??
    session?.user?.name ?? "user";
  const active = projects.find((p) => p.id === activeId) ?? null;

  if (status === "loading") return <main className="p-8 text-sm">Loading…</main>;
  if (!session) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <ProjectTracker onProjects={setProjects} />
      <Sidebar username={username} activeId={activeId} onSelect={setActiveId} />
      <Chat
        key={activeId ?? "personal"}
        project={active}
        username={username}
      />
      <Inspector project={active} />
    </div>
  );
}

// Keeps the active project object in sync with the sidebar's project list.
import { useBackend } from "@/lib/api";
function ProjectTracker({ onProjects }: { onProjects: (p: Project[]) => void }) {
  const api = useBackend();
  useEffect(() => {
    if (!api.token) return;
    api.get<{ projects: Project[] }>("/projects/mine").then(
      (d) => onProjects(d.projects),
      () => {}
    );
  }, [api.token]);
  return null;
}
