import { Binary, Calendar, Hash, ToggleLeft, Type } from "lucide-react";
import { typeKind } from "@/lib/format";
import { cn } from "@/lib/utils";

export function TypeIcon({ type, className }: { type: string; className?: string }) {
  const kind = typeKind(type);
  const Icon = kind === "number" ? Hash : kind === "temporal" ? Calendar : kind === "boolean" ? ToggleLeft : kind === "text" ? Type : Binary;
  return <Icon aria-label={type} className={cn("size-3.5 shrink-0 text-subtle", className)} />;
}
