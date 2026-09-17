import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

// FROZEN (Phase 0): credentials provider -> FastAPI POST /auth/login (bcrypt check)
// -> returns {id UUID, username, backendToken}; jwt callback stores backendToken;
// session callback exposes it; middleware protects `/`. All server fetches forward
// `Authorization: Bearer <session.backendToken>`. See AGENT_LOOP.md Phase 0.
export const { handlers, signIn, signOut, auth } = NextAuth({
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: { username: {}, password: {} },
      authorize: async (creds) => {
        const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
        const res = await fetch(`${backend}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: creds?.username, password: creds?.password })
        });
        if (!res.ok) return null;
        const data = await res.json();
        // Expected backend shape: { access_token, user: { id, username } }
        if (!data?.access_token) return null;
        return {
          id: data.user?.id ?? data.id,
          name: data.user?.username ?? data.username,
          backendToken: data.access_token
        } as unknown as import("next-auth").User;
      }
    })
  ],
  callbacks: {
    // Middleware gate: any matched route requires a session (/login excluded
    // by the middleware matcher).
    async authorized({ auth }) {
      return !!auth;
    },
    async jwt({ token, user }) {
      if (user) {
        token.id = (user as { id?: string }).id;
        token.username = user.name;
        token.backendToken = (user as unknown as { backendToken?: string }).backendToken;
      }
      return token;
    },
    async session({ session, token }) {
      (session as unknown as { backendToken?: unknown }).backendToken = token.backendToken;
      if (session.user) {
        (session.user as { id?: unknown }).id = token.id;
        (session.user as { username?: unknown }).username = token.username;
      }
      return session;
    }
  }
});
