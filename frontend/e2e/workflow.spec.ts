import { expect, test, type APIRequestContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";

const API = process.env.FACET_API_URL ?? "http://localhost:8000";
const TOKEN = process.env.FACET_TOKEN ?? "facet-dev-token";
const SAMPLE = path.resolve(__dirname, "../../samples/demo_orders.csv");
const auth = { Authorization: `Bearer ${TOKEN}` };
const unique = `e2e_${Date.now().toString(36)}`;

/** Expected values computed independently from the CSV file, not from the app. */
function expected() {
  const lines = fs.readFileSync(SAMPLE, "utf8").trim().split("\n");
  const header = lines[0]!.split(",");
  const ri = header.indexOf("region");
  const qi = header.indexOf("qty");
  const byRegion = new Map<string, number>();
  for (const l of lines.slice(1)) {
    const c = l.split(",");
    byRegion.set(c[ri]!, (byRegion.get(c[ri]!) ?? 0) + Number(c[qi]));
  }
  return { rows: lines.length - 1, columns: header.length, byRegion };
}

async function cleanup(request: APIRequestContext) {
  const list = await (await request.get(`${API}/api/v1/datasets?limit=200`, { headers: auth })).json();
  for (const d of list.items) if (String(d.name).startsWith(unique)) await request.delete(`${API}/api/v1/datasets/${d.id}`, { headers: auth });
  const dashes = await (await request.get(`${API}/api/v1/dashboards?limit=200`, { headers: auth })).json();
  for (const d of dashes.items) if (String(d.name).startsWith(unique)) await request.delete(`${API}/api/v1/dashboards/${d.id}`, { headers: auth });
  const qs = await (await request.get(`${API}/api/v1/queries?limit=200`, { headers: auth })).json();
  for (const q of qs.items) if (String(q.name).startsWith(unique)) await request.delete(`${API}/api/v1/queries/${q.id}`, { headers: auth });
}

test.afterAll(async ({ request }) => cleanup(request));

test("upload → schema → profile → SQL → chart → dashboard → export", async ({ page }) => {
  const exp = expected();

  // 1. Upload a CSV through the import dialog.
  await page.goto("/datasets");
  await page.getByTestId("open-upload").click();
  await page.getByTestId("upload-input").setInputFiles(SAMPLE);
  await page.getByLabel("Dataset name").fill(`${unique} orders`);
  await page.getByTestId("upload-submit").click();
  await page.waitForURL(/\/datasets\/[0-9a-f-]{36}/);

  // 2. Background ingest finishes and the dataset is ready with the right shape.
  await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(exp.rows.toLocaleString("en-US")).first()).toBeVisible();
  const sqlName = (await page.locator("header .font-mono").first().textContent())!.trim();

  // 3. Inferred schema.
  await page.getByRole("tab", { name: /Schema/ }).click();
  const schema = page.getByRole("table", { name: "Schema" });
  await expect(schema.locator("tbody tr")).toHaveCount(exp.columns);
  await expect(schema).toContainText("ordered_at");
  await expect(schema).toContainText("TIMESTAMP");

  // 4. Preview rows.
  await page.getByRole("tab", { name: /Preview/ }).click();
  await expect(page.getByRole("region", { name: "Dataset preview" })).toContainText("order_id");

  // 5. Profile (computed by a background job).
  await page.getByRole("tab", { name: /Profile/ }).click();
  await expect(page.getByText("unit_price").first()).toBeVisible({ timeout: 60_000 });

  // 6. Run a real aggregate query and check it against values computed from the file.
  await page.goto(`/sql?sql=${encodeURIComponent(`SELECT region, sum(qty) AS units FROM ${sqlName} GROUP BY 1 ORDER BY 1`)}`);
  await page.getByTestId("run-query").click();
  await expect(page.getByTestId("query-status")).toContainText(`${exp.byRegion.size} rows`);
  const grid = page.getByRole("region", { name: "Query results" });
  for (const [region, units] of exp.byRegion) {
    await expect(grid).toContainText(region);
    await expect(grid).toContainText(`${region}${units}`);
  }

  // 7. Save the query.
  await page.getByTestId("save-query").click();
  await page.getByLabel("Name").fill(`${unique} units by region`);
  await page.getByTestId("save-query-confirm").click();
  await expect(page.getByText(/Saved “/)).toBeVisible();

  // 8. Writes and file access are rejected by the read-only boundary.
  await page.goto(`/sql?sql=${encodeURIComponent(`DROP TABLE ${sqlName}`)}`);
  await page.getByTestId("run-query").click();
  await expect(page.getByTestId("query-error")).toBeVisible();
  await page.goto(`/sql?sql=${encodeURIComponent("SELECT * FROM read_csv('/etc/passwd')")}`);
  await page.getByTestId("run-query").click();
  await expect(page.getByTestId("query-error")).toBeVisible();

  // 9. Build and save a chart from the dataset.
  const dsId = page.url().match(/[0-9a-f-]{36}/)?.[0];
  const datasets = await (await page.request.get(`${API}/api/v1/datasets?limit=200`, { headers: auth })).json();
  const ds = datasets.items.find((d: { sql_name: string }) => d.sql_name === sqlName);
  expect(ds, dsId).toBeTruthy();
  await page.goto(`/charts/new?dataset=${ds.id}`);
  await page.getByTestId("chart-x").selectOption("region");
  await page.getByLabel("Aggregation").first().selectOption("sum");
  await page.getByLabel("Measure field").first().selectOption("qty");
  await page.getByTestId("chart-name").fill(`${unique} units chart`);
  await expect(page.locator("[data-testid=chart-canvas] .recharts-bar-rectangle")).toHaveCount(exp.byRegion.size);
  await page.getByTestId("save-chart").click();
  await page.waitForURL(/\/charts\/[0-9a-f-]{36}$/);

  // 10. Put it on a dashboard and confirm it survives a reload.
  await page.goto("/dashboards");
  await page.getByTestId("new-dashboard").click();
  await page.getByTestId("dashboard-name").fill(`${unique} dashboard`);
  await page.getByTestId("create-dashboard").click();
  await page.waitForURL(/\/dashboards\/[0-9a-f-]{36}$/);
  await page.getByTestId("add-tile").click();
  await page.getByTestId("add-chart-list").getByText(`${unique} units chart`).click();
  await expect(page.getByTestId("dashboard-tile")).toHaveCount(1);
  await page.waitForTimeout(800); // layout save is debounced
  await page.reload();
  await expect(page.getByTestId("dashboard-tile")).toHaveCount(1);
  await expect(page.locator(".recharts-bar-rectangle")).toHaveCount(exp.byRegion.size);

  // 11. Export the dataset as CSV and check the downloaded file.
  await page.goto(`/datasets/${ds.id}`);
  const download = page.waitForEvent("download");
  await page.getByTestId("export-menu").click();
  await page.getByTestId("export-csv").click();
  const file = await (await download).path();
  const exported = fs.readFileSync(file!, "utf8").trim().split("\n");
  expect(exported.length).toBe(exp.rows + 1);

  // Accessibility smoke check on the final page.
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);
});

test("another user cannot see this workspace's data", async ({ request }) => {
  const r = await request.get(`${API}/api/v1/datasets`, { headers: { Authorization: "Bearer not-a-real-token" } });
  expect(r.status()).toBe(401);
});
