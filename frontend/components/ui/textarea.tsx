// ReUI Base UI Textarea — native textarea styled as ReUI. No Radix.
import * as React from "react";
import { cn } from "@/lib/utils";

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn("flex min-h-[60px] w-full rounded-md border px-3 py-2 text-sm outline-none", className)}
      {...props}
    />
  );
}
