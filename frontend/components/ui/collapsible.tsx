// ReUI Skeleton + Collapsible — Skeleton is a styled div; Collapsible wraps @base-ui/react. No Radix.
"use client";
import * as React from "react";
import { Collapsible as BaseCollapsible } from "@base-ui/react/collapsible";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-neutral-200", className)} />;
}

export function WhyCollapsible({ children }: { children: React.ReactNode }) {
  return (
    <BaseCollapsible.Root className="mt-1 text-xs">
      <BaseCollapsible.Trigger className="text-neutral-500 underline">
        Why this answer?
      </BaseCollapsible.Trigger>
      <BaseCollapsible.Panel className="mt-1 rounded-md bg-neutral-50 p-2 text-neutral-700">
        {children}
      </BaseCollapsible.Panel>
    </BaseCollapsible.Root>
  );
}
