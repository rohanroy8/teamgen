import { auth } from "@/auth";
import { redirect } from "next/navigation";

export default async function Home() {
  const session = await auth();
  if (!session) redirect("/login");
  const username = (session.user as { username?: string })?.username ?? "user";
  return (
    <main className="p-8">
      <h1 className="text-2xl font-bold">teamgen-memory — Phase 0</h1>
      <p className="mt-2">Signed in as @{username}. Chat + Inspector land in Phase 6.</p>
    </main>
  );
}
