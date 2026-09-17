// ReUI Base UI Input — wraps @base-ui/react Input primitive. No Radix.
import * as React from "react";
import { Input as BaseInput } from "@base-ui/react/input";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<typeof BaseInput>) {
  return (
    <BaseInput
      className={cn("flex h-9 w-full rounded-md border px-3 py-1 text-sm outline-none", className)}
      {...props}
    />
  );
}
