import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "teamgen-memory", description: "Phase 0 stub" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
