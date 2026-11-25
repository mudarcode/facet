import { Badge } from "@/components/ui/badge";
import type { DatasetStatus } from "@/lib/types";

export function StatusBadge({ status }: { status: DatasetStatus }) {
  switch (status) {
    case "ready":
      return <Badge tone="success">Ready</Badge>;
    case "failed":
      return <Badge tone="danger">Failed</Badge>;
    case "processing":
      return (
        <Badge tone="accent">
          <span className="size-1.5 animate-pulse rounded-full bg-current" /> Processing
        </Badge>
      );
    case "pending":
      return <Badge tone="neutral">Queued</Badge>;
    default:
      return <Badge>{status}</Badge>;
  }
}
