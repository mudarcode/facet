"use client";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { typeKind } from "@/lib/format";
import type { ColumnSchema, Condition, FilterOp } from "@/lib/types";

const OPS: { op: FilterOp; label: string }[] = [
  { op: "=", label: "=" },
  { op: "!=", label: "≠" },
  { op: ">", label: ">" },
  { op: ">=", label: "≥" },
  { op: "<", label: "<" },
  { op: "<=", label: "≤" },
  { op: "contains", label: "contains" },
  { op: "not_contains", label: "doesn't contain" },
  { op: "starts_with", label: "starts with" },
  { op: "ends_with", label: "ends with" },
  { op: "in", label: "is one of" },
  { op: "not_in", label: "is not one of" },
  { op: "is_null", label: "is empty" },
  { op: "is_not_null", label: "is not empty" },
];

const NO_VALUE: FilterOp[] = ["is_null", "is_not_null"];

/** Parse the text box into a typed value for the column (numbers stay numbers). */
export function parseValue(raw: string, type: string | undefined, op: FilterOp): unknown {
  const kind = type ? typeKind(type) : "text";
  const one = (s: string): unknown => {
    const t = s.trim();
    if (kind === "number" && t !== "" && !Number.isNaN(Number(t))) return Number(t);
    if (kind === "boolean") return t.toLowerCase() === "true";
    return t;
  };
  if (op === "in" || op === "not_in") return raw.split(",").map(one).filter((v) => v !== "");
  return one(raw);
}

export function displayValue(v: unknown): string {
  if (Array.isArray(v)) return v.join(", ");
  if (v === null || v === undefined) return "";
  return String(v);
}

export function ConditionsEditor({
  columns,
  value,
  onChange,
  addLabel = "Add filter",
  compact,
}: {
  columns: ColumnSchema[];
  value: Condition[];
  onChange: (c: Condition[]) => void;
  addLabel?: string;
  compact?: boolean;
}) {
  const typeOf = (name: string) => columns.find((c) => c.name === name)?.type;
  const set = (i: number, patch: Partial<Condition>) => onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div className="space-y-2">
      {value.map((c, i) => (
        <div key={i} className={compact ? "flex flex-wrap items-center gap-1.5" : "grid grid-cols-[1fr_auto] gap-1.5"} data-testid="condition-row">
          <div className={compact ? "contents" : "grid grid-cols-2 gap-1.5"}>
            <NativeSelect
              aria-label="Filter column"
              className={compact ? "h-7 w-36 text-xs" : "text-xs"}
              value={c.column}
              onChange={(e) => set(i, { column: e.target.value })}
            >
              {columns.map((col) => (
                <option key={col.name} value={col.name}>
                  {col.name}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="Filter operator"
              className={compact ? "h-7 w-32 text-xs" : "text-xs"}
              value={c.op}
              onChange={(e) => {
                const op = e.target.value as FilterOp;
                set(i, { op, value: NO_VALUE.includes(op) ? undefined : parseValue(displayValue(c.value), typeOf(c.column), op) });
              }}
            >
              {OPS.map((o) => (
                <option key={o.op} value={o.op}>
                  {o.label}
                </option>
              ))}
            </NativeSelect>
            {NO_VALUE.includes(c.op) ? null : (
              <Input
                key={`${i}:${c.column}:${displayValue(c.value)}`}
                aria-label="Filter value"
                className={compact ? "h-7 w-36 text-xs" : "col-span-2 text-xs"}
                placeholder={c.op === "in" || c.op === "not_in" ? "a, b, c" : "value"}
                defaultValue={displayValue(c.value)}
                onBlur={(e) => set(i, { value: parseValue(e.target.value, typeOf(c.column), c.op) })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") set(i, { value: parseValue(e.currentTarget.value, typeOf(c.column), c.op) });
                }}
              />
            )}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Remove filter" onClick={() => onChange(value.filter((_, j) => j !== i))}>
            <X />
          </Button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        disabled={!columns.length}
        onClick={() => onChange([...value, { column: columns[0]!.name, op: "=", value: "" }])}
        data-testid="add-condition"
      >
        <Plus /> {addLabel}
      </Button>
    </div>
  );
}

/** Conditions that are complete enough to send to the API. */
export function completeConditions(cs: Condition[]): Condition[] {
  return cs.filter((c) => {
    if (NO_VALUE.includes(c.op)) return true;
    if (Array.isArray(c.value)) return c.value.length > 0;
    return c.value !== "" && c.value !== undefined && c.value !== null;
  });
}
