"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { ErrorBanner } from "@/components/ui/feedback";
import { api, ApiError } from "@/lib/api";
import type { QueryResult } from "@/lib/types";
import { ExportMenu } from "@/features/exports/export-menu";

export function SqlToolbarExtras({
  sql,
  savedQueryId,
  onSaved,
  lastResult,
  lastSql,
}: {
  sql: string;
  savedQueryId: string | null;
  onSaved: (id: string) => void;
  lastResult: QueryResult | null;
  lastSql: string;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const saveExisting = async () => {
    if (!savedQueryId) return setOpen(true);
    try {
      await api.updateSavedQuery(savedQueryId, { sql });
      qc.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Saved query updated");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const q = await api.createSavedQuery({ name: name.trim(), sql });
      qc.invalidateQueries({ queryKey: ["saved-queries"] });
      onSaved(q.id);
      setOpen(false);
      setName("");
      toast.success(`Saved “${q.name}”`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {lastResult ? <ExportMenu source={{ kind: "query", sql: lastSql }} /> : null}
      <Button variant="outline" onClick={saveExisting} data-testid="save-query">
        <Save /> {savedQueryId ? "Save" : "Save as…"}
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Save query"
        description="Saved queries can be reopened, shared across sessions and used as chart sources."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={create} loading={busy} disabled={!name.trim()} data-testid="save-query-confirm">
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-1.5">
          <Label htmlFor="sq-name">Name</Label>
          <Input id="sq-name" autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && name.trim() && create()} placeholder="e.g. Revenue by region" />
        </div>
        {error ? <ErrorBanner className="mt-3" message={error} /> : null}
      </Dialog>
    </>
  );
}
