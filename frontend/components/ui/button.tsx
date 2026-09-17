// ReUI Base UI Button — wraps @base-ui/react Button primitive. No Radix.
import * as React from "react";
import { Button as BaseButton } from "@base-ui/react/button";
import { cn } from "@/lib/utils";

export function Button({ className, ...props }: React.ComponentProps<typeof BaseButton>) {
  return (
    <BaseButton
      className={cn(
        "inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
}
