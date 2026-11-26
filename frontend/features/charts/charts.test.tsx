import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ChartData, ChartSpec, ColumnSchema, Condition } from "@/lib/types";
import { completeConditions, ConditionsEditor, parseValue } from "./conditions-editor";
import { formatTick, formatX, shape, StatCards } from "./chart-view";
import { retype, specReady } from "./chart-builder";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const COLS: ColumnSchema[] = [
  { name: "order_id", type: "BIGINT" },
  { name: "region", type: "VARCHAR" },
  { name: "qty", type: "INTEGER" },
  { name: "price", type: "DOUBLE" },
  { name: "ordered_at", type: "TIMESTAMP" },
];

const data = (over: Partial<ChartData>): ChartData => ({
  columns: [],
  rows: [],
  meta: { type: "bar", x: "x", measures: ["y"], series: null, truncated: false },
  sql: "",
  engine_ms: 1,
  total_ms: 2,
  ...over,
});

describe("filter values", () => {
  it("keeps numbers numeric for numeric columns and splits lists", () => {
    expect(parseValue("42", "BIGINT", "=")).toBe(42);
    expect(parseValue("42", "VARCHAR", "=")).toBe("42");
    expect(parseValue("a, b,,c", "VARCHAR", "in")).toEqual(["a", "b", "c"]);
    expect(parseValue("1,2", "INTEGER", "not_in")).toEqual([1, 2]);
    expect(parseValue("TRUE", "BOOLEAN", "=")).toBe(true);
  });

  it("drops incomplete conditions before sending", () => {
    const cs: Condition[] = [
      { column: "region", op: "=", value: "" },
      { column: "region", op: "is_null" },
      { column: "region", op: "in", value: [] },
      { column: "qty", op: ">", value: 3 },
    ];
    expect(completeConditions(cs)).toEqual([cs[1], cs[3]]);
  });

  it("adds and edits a condition through the UI", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [v, setV] = useState<Condition[]>([]);
      return (
        <>
          <ConditionsEditor columns={COLS} value={v} onChange={setV} />
          <output data-testid="out">{JSON.stringify(v)}</output>
        </>
      );
    }
    render(<Harness />);
    await user.click(screen.getByTestId("add-condition"));
    await user.selectOptions(screen.getByLabelText("Filter column"), "qty");
    await user.selectOptions(screen.getByLabelText("Filter operator"), ">=");
    await user.type(screen.getByLabelText("Filter value"), "5{Enter}");
    expect(JSON.parse(screen.getByTestId("out").textContent!)).toEqual([{ column: "qty", op: ">=", value: 5 }]);
    await user.click(screen.getByLabelText("Remove filter"));
    expect(screen.getByTestId("out").textContent).toBe("[]");
  });
});

describe("chart data shaping", () => {
  it("pivots series rows and orders series by total with Other last", () => {
    const s = shape(
      data({
        meta: { type: "line", x: "x", measures: ["y"], series: "series", truncated: false },
        rows: [
          ["2024-01", "Other", 100],
          ["2024-01", "A", 5],
          ["2024-01", "B", 9],
          ["2024-02", "A", 6],
          ["2024-02", "B", 1],
        ],
      }),
    );
    expect(s.keys).toEqual(["A", "B", "Other"]);
    expect(s.rows).toEqual([
      { __x: "2024-01", Other: 100, A: 5, B: 9 },
      { __x: "2024-02", A: 6, B: 1 },
    ]);
  });

  it("maps multi-measure rows to keyed objects", () => {
    const s = shape(data({ meta: { type: "bar", x: "x", measures: ["sum_qty", "count"], series: null, truncated: false }, rows: [["North", 10, 2]] }));
    expect(s.rows).toEqual([{ __x: "North", sum_qty: 10, count: 2 }]);
  });

  it("formats ticks and temporal labels", () => {
    expect(formatTick(22.3231)).toBe("22.3");
    expect(formatTick(130.8)).toBe("131");
    expect(formatTick(0.123)).toBe("0.12");
    expect(formatTick(1_500_000)).toBe("1.5M");
    expect(formatX("2024-03-01", "month")).toBe("Mar 2024");
    expect(formatX("2024-04-01", "quarter")).toBe("Q2 2024");
    expect(formatX(null)).toBe("(null)");
  });

  it("renders stat cards from the first row", () => {
    render(<StatCards data={data({ meta: { type: "stat", x: null, measures: ["count", "avg_price"], series: null, truncated: false }, rows: [[1262, 54.567]] })} />);
    const values = screen.getAllByTestId("stat-value").map((e) => e.textContent);
    expect(values).toEqual(["1,262", "54.57"]);
  });
});

describe("chart spec helpers", () => {
  const base: ChartSpec = { type: "bar", x: null, y: [{ field: null, agg: "count" }], grain: "none", filters: [], options: {} };

  it("picks sensible defaults per chart type and skips identifier columns", () => {
    const bar = retype(base, "bar", COLS);
    expect(bar.x).toBe("region");
    const line = retype(bar, "line", COLS);
    expect(line.x).toBe("ordered_at");
    const scatter = retype(base, "scatter", COLS);
    expect(scatter.x).toBe("qty");
    expect(scatter.y).toEqual([{ field: "price", agg: "min" }]);
    const hist = retype(base, "histogram", COLS);
    expect(hist.x).toBe("qty");
    expect(hist.y).toEqual([]);
    expect(retype(base, "stat", COLS).x).toBeNull();
  });

  it("explains what is missing before a preview is requested", () => {
    expect(specReady({ ...base, x: null })).toMatch(/x-axis/);
    expect(specReady({ ...base, type: "stat", y: [] })).toMatch(/measure/);
    expect(specReady({ ...base, type: "scatter", x: "qty", y: [] })).toMatch(/numeric field/);
    expect(specReady({ ...base, x: "region" })).toBeNull();
  });
});
