// @ts-nocheck — NextAuth v5 beta type shim for Phase 0 scaffold
declare module "next-auth" {
  interface User {
    backendToken?: string;
  }
}
export {};
