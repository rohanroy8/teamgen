// ReUI Base UI Badge — status pill. No Radix.
import * as React from "react";
import { cn } from "@/lib/utils";

const tones: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  proposed: "bg-yellow-100 text-yellow-800",
  superseded: "bg-gray-200 text-gray-600 line-through",
  disputed: "bg-orange-100 text-orange-800",
  retracted: "bg-red-100 text-red-800",
  forgotten: "bg-red-100 text-red-800",
  stale: "bg-gray-100 text-gray-500",
  rejected: "bg-red-100 text-red-800",
  personal: "bg-blue-100 text-blue-800",
  project: "bg-purple-100 text-purple-800",
  pinned: "bg-amber-100 text-amber-800"
};

export function Badge({ tone, className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: string }) {
  return (
    <span
      className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone ?? ""] ?? "bg-gray-100 text-gray-700", className)}
      {...props}
    />
  );
}
