// ReUI Base UI Tabs — wraps @base-ui/react Tabs primitive. No Radix.
"use client";
import * as React from "react";
import { Tabs as BaseTabs } from "@base-ui/react/tabs";
import { cn } from "@/lib/utils";

export function Tabs({ tabs, defaultValue }: {
  tabs: { value: string; label: string; content: React.ReactNode }[];
  defaultValue?: string;
}) {
  return (
    <BaseTabs.Root defaultValue={defaultValue ?? tabs[0]?.value} className="flex h-full flex-col">
      <BaseTabs.List className="flex gap-1 border-b">
        {tabs.map((t) => (
          <BaseTabs.Tab
            key={t.value}
            value={t.value}
            className={cn("px-3 py-2 text-sm text-neutral-500 data-[selected]:border-b-2 data-[selected]:border-neutral-900 data-[selected]:text-neutral-900")}
          >
            {t.label}
          </BaseTabs.Tab>
        ))}
      </BaseTabs.List>
      {tabs.map((t) => (
        <BaseTabs.Panel key={t.value} value={t.value} className="min-h-0 flex-1 overflow-y-auto p-3">
          {t.content}
        </BaseTabs.Panel>
      ))}
    </BaseTabs.Root>
  );
}
