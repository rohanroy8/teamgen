// ReUI Base UI Avatar — wraps @base-ui/react Avatar primitive. No Radix.
import * as React from "react";
import { Avatar as BaseAvatar } from "@base-ui/react/avatar";
import { cn } from "@/lib/utils";

export function Avatar({ username, className }: { username: string; className?: string }) {
  const initials = username.slice(0, 2).toUpperCase();
  return (
    <BaseAvatar.Root
      className={cn("inline-flex h-7 w-7 items-center justify-center rounded-full bg-neutral-800 text-xs font-medium text-white", className)}
      title={`@${username}`}
    >
      <BaseAvatar.Fallback>{initials}</BaseAvatar.Fallback>
    </BaseAvatar.Root>
  );
}
