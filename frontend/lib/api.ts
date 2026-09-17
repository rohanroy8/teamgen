"use client";
// Client-side backend API: bearer token comes from the NextAuth session
// (session.backendToken), forwarded as Authorization on every request.
import { useSession } from "next-auth/react";

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export function useBackend() {
  const { data: session } = useSession();
  const token = (session as unknown as { backendToken?: string } | null)?.backendToken;

  async function call<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers as Record<string, string> | undefined),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
    }
    return res.json() as Promise<T>;
  }

  return {
    token,
    get: <T,>(p: string) => call<T>(p),
    post: <T,>(p: string, body: unknown) =>
      call<T>(p, { method: "POST", body: JSON.stringify(body) }),
    del: <T,>(p: string) => call<T>(p, { method: "DELETE" })
  };
}

export type Project = { id: string; name: string; role: string };
export type MemoryRow = {
  id: string; subject: string; predicate: string; object: string; status: string;
  scope: string; valid_from: string; valid_to: string | null; recorded_at: string;
  confidence: number | null; quote: string | null; author: string;
};
export type ConflictRow = {
  id: string; status: string; note: string | null;
  memory_a: MemoryRow | null; memory_b: MemoryRow | null;
  winner_id: string | null; resolver: string | null;
};
