import { describe, expect, it } from "vitest";
import { formatBytes, formatCell, formatCompact, formatMs, formatNumber, typeKind } from "./format";

describe("format helpers", () => {
  it("formats numbers and missing values", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatNumber(null)).toBe("—");
    expect(formatCompact(9999)).toBe("9,999");
    expect(formatCompact(1_250_000)).toBe("1.3M");
  });

  it("formats bytes with binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
  });

  it("formats durations", () => {
    expect(formatMs(0.4)).toBe("<1 ms");
    expect(formatMs(12.6)).toBe("13 ms");
    expect(formatMs(2500)).toBe("2.50 s");
  });

  it("maps DuckDB types to kinds", () => {
    expect(typeKind("BIGINT")).toBe("number");
    expect(typeKind("DECIMAL(18,4)")).toBe("number");
    expect(typeKind("TIMESTAMP WITH TIME ZONE")).toBe("temporal");
    expect(typeKind("VARCHAR")).toBe("text");
    expect(typeKind("BOOLEAN")).toBe("boolean");
    expect(typeKind("STRUCT(a INTEGER)")).toBe("other");
  });

  it("renders cells without losing meaning", () => {
    expect(formatCell(null)).toBe("");
    expect(formatCell(0.1 + 0.2)).toBe("0.3");
    expect(formatCell({ a: 1 })).toBe("{\"a\":1}");
    expect(formatCell(true)).toBe("true");
  });
});
