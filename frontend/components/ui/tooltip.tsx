"use client";
import { Tooltip as T } from "radix-ui";
import type { ReactNode } from "react";

export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <T.Root delayDuration={250}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className="z-50 rounded-md bg-fg px-2 py-1 text-[11px] font-medium text-bg shadow-md">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
