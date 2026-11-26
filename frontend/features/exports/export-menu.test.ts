import { beforeEach, describe, expect, it, vi } from "vitest";

const createExport = vi.fn();
const getExport = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { createExport: (...a: unknown[]) => createExport(...a), getExport: (...a: unknown[]) => getExport(...a) },
  absoluteUrl: (p: string) => `http://api.test${p}`,
}));

import { runExport } from "./export-menu";

const rec = (status: string, extra: object = {}) => ({ id: "e1", status, filename: "x.csv", download_url: null, error: null, ...extra });

describe("runExport", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    createExport.mockReset();
    getExport.mockReset();
  });

  it("polls until the job succeeds, then downloads via the signed link", async () => {
    createExport.mockResolvedValue(rec("queued"));
    getExport.mockResolvedValueOnce(rec("running")).mockResolvedValueOnce(rec("succeeded", { download_url: "/api/v1/exports/e1/download?expires=1&sig=a" }));
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.href);
    });
    const p = runExport({ kind: "query", sql: "SELECT 1" }, "csv");
    await vi.runAllTimersAsync();
    const r = await p;
    expect(r.status).toBe("succeeded");
    expect(getExport).toHaveBeenCalledTimes(2);
    expect(clicks).toEqual(["http://api.test/api/v1/exports/e1/download?expires=1&sig=a"]);
  });

  it("surfaces the server's error when the export fails", async () => {
    createExport.mockResolvedValue(rec("queued"));
    getExport.mockResolvedValue(rec("failed", { error: "Export failed: disk full" }));
    const p = runExport({ kind: "dataset", dataset_id: "d" }, "parquet");
    const assertion = expect(p).rejects.toThrow("disk full");
    await vi.runAllTimersAsync();
    await assertion;
  });
});
