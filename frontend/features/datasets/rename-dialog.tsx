"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { ErrorBanner } from "@/components/ui/feedback";
import type { Dataset } from "@/lib/types";
import { useRenameDataset } from "./hooks";

const SQL_NAME = /^[a-z_][a-z0-9_]{0,62}$/;

export function RenameDialog({ dataset, onClose }: { dataset: Dataset | null; onClose: () => void }) {
  // Re-mount the form per dataset so its fields start from that dataset's values.
  return <RenameForm key={dataset?.id ?? "none"} dataset={dataset} onClose={onClose} />;
}

function RenameForm({ dataset, onClose }: { dataset: Dataset | null; onClose: () => void }) {
  const [name, setName] = useState(dataset?.name ?? "");
  const [sqlName, setSqlName] = useState(dataset?.sql_name ?? "");
  const [description, setDescription] = useState(dataset?.description ?? "");
  const rename = useRenameDataset();
  const validSql = SQL_NAME.test(sqlName);

  const save = async () => {
    if (!dataset) return;
    try {
      await rename.mutateAsync({ id: dataset.id, name: name.trim(), sql_name: sqlName, description });
      toast.success("Dataset updated");
      onClose();
    } catch {
      /* shown inline */
    }
  };

  return (
    <Dialog
      open={!!dataset}
      onOpenChange={(o) => !o && onClose()}
      title="Edit dataset"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} loading={rename.isPending} disabled={!name.trim() || !validSql}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="rn-name">Display name</Label>
          <Input id="rn-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="rn-sql">SQL name</Label>
          <Input id="rn-sql" className="font-mono" value={sqlName} onChange={(e) => setSqlName(e.target.value.toLowerCase())} aria-invalid={!validSql} />
          <p className={validSql ? "text-xs text-subtle" : "text-xs text-danger"}>
            {validSql ? "Used in queries: SELECT * FROM " + sqlName : "Lowercase letters, digits and underscores; must not start with a digit."}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="rn-desc">Description</Label>
          <textarea
            id="rn-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-border bg-surface px-2.5 py-2 text-[13px] shadow-sm focus:border-accent focus:ring-3 focus:ring-[var(--ring)] focus:outline-none"
          />
        </div>
        {rename.error ? <ErrorBanner message={(rename.error as Error).message} /> : null}
      </div>
    </Dialog>
  );
}
