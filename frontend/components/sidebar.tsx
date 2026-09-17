// Sidebar: user card, New Project, project list, per-project Invite-by-username.
"use client";
import { useEffect, useState } from "react";
import { signOut } from "next-auth/react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { useBackend, type Project } from "@/lib/api";

export function Sidebar({ username, activeId, onSelect }: {
  username: string; activeId: string | null; onSelect: (id: string | null) => void;
}) {
  const api = useBackend();
  const [projects, setProjects] = useState<Project[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [inviteFor, setInviteFor] = useState<Project | null>(null);
  const [inviteName, setInviteName] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh() {
    try {
      const d = await api.get<{ projects: Project[] }>("/projects/mine");
      setProjects(d.projects);
    } catch {
      /* backend may be down; keep list */
    }
  }
  useEffect(() => { if (api.token) refresh(); }, [api.token]);

  async function createProject() {
    if (!newName.trim()) return;
    try {
      await api.post("/projects", { name: newName.trim() });
      setNewName("");
      setShowNew(false);
      refresh();
    } catch (e) {
      setNotice(String(e));
    }
  }

  async function invite() {
    if (!inviteFor || !inviteName.trim()) return;
    try {
      await api.post(`/projects/${inviteFor.id}/invite`, { username: inviteName.trim() });
      setNotice(`@${inviteName.trim()} joined ${inviteFor.name}`);
      setInviteName("");
      setInviteFor(null);
    } catch (e) {
      setNotice(String(e));
    }
  }

  return (
    <aside className="flex w-64 flex-col border-r bg-neutral-50 p-3">
      <div className="mb-3 flex items-center gap-2">
        <Avatar username={username} />
        <span className="text-sm font-medium">@{username}</span>
        <button className="ml-auto text-xs text-neutral-500 underline" onClick={() => signOut({ callbackUrl: "/login" })}>
          logout
        </button>
      </div>
      <Button onClick={() => setShowNew(true)}>+ New Project</Button>
      <button
        onClick={() => onSelect(null)}
        className={`mt-3 rounded-md px-2 py-1.5 text-left text-sm ${activeId === null ? "bg-neutral-200 font-medium" : "hover:bg-neutral-100"}`}
      >
        Personal
      </button>
      <div className="mt-1 flex flex-col gap-0.5 overflow-y-auto">
        {projects.map((p) => (
          <div key={p.id} className={`flex items-center rounded-md px-2 py-1.5 text-sm ${activeId === p.id ? "bg-neutral-200 font-medium" : "hover:bg-neutral-100"}`}>
            <button className="flex-1 text-left" onClick={() => onSelect(p.id)}>
              {p.name} <span className="text-xs text-neutral-400">· {p.role}</span>
            </button>
            <button className="text-xs text-neutral-500 underline" title="Invite by username" onClick={() => { setInviteFor(p); setInviteName(""); }}>
              Invite
            </button>
          </div>
        ))}
      </div>
      {notice ? <p className="mt-2 text-xs text-neutral-600">{notice}</p> : null}

      <Dialog open={showNew} onOpenChange={setShowNew} title="New Project">
        <Input placeholder="project name" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <div className="mt-3 flex justify-end gap-2">
          <Button onClick={createProject}>Create</Button>
        </div>
      </Dialog>

      <Dialog open={inviteFor !== null} onOpenChange={(o) => { if (!o) setInviteFor(null); }} title={`Invite to ${inviteFor?.name ?? ""}`}>
        <Input placeholder="username (exact, case-insensitive)" value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
        <div className="mt-3 flex justify-end gap-2">
          <Button onClick={invite}>Invite</Button>
        </div>
      </Dialog>
    </aside>
  );
}
