// ReUI Base UI Dialog — wraps @base-ui/react Dialog primitive. No Radix.
"use client";
import * as React from "react";
import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import { cn } from "@/lib/utils";

export function Dialog({ open, onOpenChange, title, children }: {
  open?: boolean; onOpenChange?: (open: boolean) => void; title: string;
  children: React.ReactNode;
}) {
  return (
    <BaseDialog.Root open={open} onOpenChange={onOpenChange}>
      <BaseDialog.Portal>
        <BaseDialog.Backdrop className="fixed inset-0 bg-black/40" />
        <BaseDialog.Popup className={cn("fixed left-1/2 top-1/2 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-white p-6 shadow-xl")}>
          <BaseDialog.Title className="mb-4 text-base font-semibold">{title}</BaseDialog.Title>
          {children}
        </BaseDialog.Popup>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  );
}
