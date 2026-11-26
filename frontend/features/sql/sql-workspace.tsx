"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, ListTree } from "lucide-react";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { api, ApiError } from "@/lib/api";
import type { QueryResult } from "@/lib/types";
import { useDatasets } from "@/features/datasets/hooks";
import { SqlEditor } from "./sql-editor";
import { ResultsPanel, type RunState } from "./results-panel";
import { SidePanel } from "./side-panel";
import { SqlToolbarExtras } from "./toolbar-extras";

const DRAFT_KEY = "facet-sql-draft";
const PAGE = 100;

function readDraft(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(DRAFT_KEY);
  } catch {
    return null;
  }
}

const STARTER = "-- Write DuckDB SQL against your datasets.\n-- Ctrl/⌘ + Enter to run.\nSELECT 42 AS answer";

/** Initial editor content: ?dataset= deep link > ?sql= > saved draft > starter query. */
function initialSql(params: URLSearchParams | { get(k: string): string | null }): string {
  const ds = params.get("dataset");
  if (ds) return `SELECT *\nFROM ${ds}\nLIMIT 100`;
  return params.get("sql") ?? readDraft() ?? STARTER;
}

export function SqlWorkspace() {
  const params = useSearchParams();
  const { data: datasets } = useDatasets();
  const paramKey = params.toString();
  const [sql, setSql] = useState(() => initialSql(params));
  const [seenParams, setSeenParams] = useState(paramKey);
  if (seenParams !== paramKey) {
    // A deep link (?dataset= / ?sql=) replaces the editor content.
    setSeenParams(paramKey);
    setSql(initialSql(params));
  }
  const [state, setState] = useState<RunState>({ status: "idle" });
  const [plan, setPlan] = useState<string | null>(null);
  const [savedQueryId, setSavedQueryId] = useState<string | null>(null);
  // ?saved=<id> opens a saved query once the list has loaded (derived state, no effect).
  const savedParam = params.get("saved");
  const savedList = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.savedQueries(), enabled: !!savedParam });
  const [appliedSaved, setAppliedSaved] = useState<string | null>(null);
  if (savedParam && appliedSaved !== savedParam && savedList.data) {
    setAppliedSaved(savedParam);
    const q = savedList.data.items.find((x) => x.id === savedParam);
    if (q) {
      setSql(q.sql);
      setSavedQueryId(q.id);
    }
  }
  const [lastSql, setLastSql] = useState("");
  const [editorHeight, setEditorHeight] = useState(260);

  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(DRAFT_KEY, sql);
      } catch {
        /* ignore */
      }
    }, 400);
    return () => clearTimeout(t);
  }, [sql]);

  const ready = useMemo(() => (datasets?.items ?? []).filter((d) => d.status === "ready"), [datasets]);
  const schema = useMemo(
    () => Object.fromEntries(ready.map((d) => [d.sql_name, (d.current_version?.columns ?? []).map((c) => c.name)])),
    [ready],
  );

  const run = useCallback(
    async (offset = 0, text?: string) => {
      const q = (text ?? sql).trim();
      if (!q) return;
      setLastSql(q);
      setPlan(null);
      setState((s) => ({ status: "running", previous: s.status === "success" && offset !== 0 ? s.result : undefined }));
      const started = performance.now();
      try {
        const result: QueryResult = await api.execute(q, offset, PAGE, {
          saved_query_id: savedQueryId ?? undefined,
          record_history: offset === 0,
        });
        setState({ status: "success", result, roundTripMs: performance.now() - started });
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
        setState({ status: "error", error: err, roundTripMs: performance.now() - started });
      }
    },
    [sql, savedQueryId],
  );

  const explain = useMutation({
    mutationFn: () => api.explain(sql),
    onSuccess: (r) => setPlan(r.plan),
    onError: (e) => setState({ status: "error", error: e as ApiError }),
  });

  const runCurrent = useCallback(() => void run(0), [run]);

  // Drag handle between editor and results.
  const onDrag = (e: React.PointerEvent) => {
    const startY = e.clientY;
    const startH = editorHeight;
    const move = (ev: PointerEvent) => setEditorHeight(Math.min(600, Math.max(120, startH + ev.clientY - startY)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <>
      <PageHeader
        title="SQL workspace"
        description="Read-only DuckDB SQL over your datasets, sandboxed per query"
        actions={
          <>
            <SqlToolbarExtras
              sql={sql}
              savedQueryId={savedQueryId}
              onSaved={(id) => setSavedQueryId(id)}
              lastResult={state.status === "success" ? state.result : null}
              lastSql={lastSql}
            />
            <Tooltip content="Show the DuckDB query plan">
              <Button variant="outline" onClick={() => explain.mutate()} loading={explain.isPending}>
                <ListTree /> Explain
              </Button>
            </Tooltip>
            <Tooltip content="Run (Ctrl/⌘ + Enter)">
              <Button variant="primary" onClick={runCurrent} loading={state.status === "running"} data-testid="run-query">
                <Play /> Run
              </Button>
            </Tooltip>
          </>
        }
      />
      <div className="flex min-h-0 flex-1">
        <SidePanel
          datasets={ready}
          onInsert={(text) => setSql((s) => (s.trim() ? `${s}${s.endsWith("\n") ? "" : "\n"}${text}` : text))}
          onOpen={(q, id) => {
            setSql(q);
            setSavedQueryId(id ?? null);
          }}
          activeSavedId={savedQueryId}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <div style={{ height: editorHeight }} className="min-h-0 shrink-0 overflow-hidden border-b border-border">
            <SqlEditor value={sql} onChange={setSql} onRun={runCurrent} schema={schema} />
          </div>
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize editor"
            onPointerDown={onDrag}
            className="-mt-1 h-2 shrink-0 cursor-row-resize bg-transparent hover:bg-accent/20"
          />
          <ResultsPanel state={state} plan={plan} onPage={(o) => run(o, lastSql)} pageSize={PAGE} onClosePlan={() => setPlan(null)} />
        </div>
      </div>
    </>
  );
}
