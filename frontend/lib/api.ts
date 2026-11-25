/**
 * Typed client for the Facet API. All requests go straight to the FastAPI server
 * (CORS-enabled) so large uploads stream without passing through Next.js.
 */
import type { Dataset, IngestOptions, Job, Page, Preview, QueryResult, ColumnSchema, DatasetVersion, ProfileResponse, SavedQuery, QueryRun, Transformation, TransformPreview, TransformStep, Chart, ChartData, ChartSource, ChartSpec, Condition, Dashboard, ExportRecord, ExportSource, LayoutItem } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN = process.env.NEXT_PUBLIC_FACET_TOKEN ?? "facet-dev-token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${TOKEN}` };
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code: string; message: string; details?: unknown } };
    if (body.error) return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
  } catch {
    /* fall through */
  }
  return new ApiError(res.status, "http_error", `Request failed (${res.status})`);
}

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1${path}`, {
      ...rest,
      headers: {
        ...authHeaders(),
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the Facet API. Is the backend running?");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface UploadHandle {
  promise: Promise<{ dataset: Dataset; job_id: string }>;
  abort: () => void;
}

/** Upload with progress via XHR (fetch has no upload progress events). */
export function uploadDataset(
  file: File,
  opts: { name?: string; options?: IngestOptions },
  onProgress: (fraction: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const params = new URLSearchParams({ filename: file.name });
  if (opts.name) params.set("name", opts.name);
  if (opts.options && Object.keys(opts.options).length) params.set("options", JSON.stringify(opts.options));
  const promise = new Promise<{ dataset: Dataset; job_id: string }>((resolve, reject) => {
    xhr.open("POST", `${API_URL}/api/v1/datasets?${params.toString()}`);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as { dataset: Dataset; job_id: string });
      else {
        const err = (body as { error?: { code: string; message: string; details?: unknown } } | null)?.error;
        reject(new ApiError(xhr.status, err?.code ?? "http_error", err?.message ?? `Upload failed (${xhr.status})`, err?.details));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Upload failed: connection lost."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload cancelled."));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}

export const api = {
  listDatasets: (q?: string) => request<Page<Dataset>>(`/datasets?limit=200${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  getDataset: (id: string) => request<Dataset>(`/datasets/${id}`),
  patchDataset: (id: string, body: Partial<Pick<Dataset, "name" | "sql_name" | "description">>) =>
    request<Dataset>(`/datasets/${id}`, { method: "PATCH", json: body }),
  deleteDataset: (id: string) => request<void>(`/datasets/${id}`, { method: "DELETE" }),
  schema: (id: string) => request<ColumnSchema[]>(`/datasets/${id}/schema`),
  versions: (id: string) => request<DatasetVersion[]>(`/datasets/${id}/versions`),
  reprocess: (id: string, options: IngestOptions) =>
    request<{ dataset: Dataset; job_id: string }>(`/datasets/${id}/reprocess`, { method: "POST", json: { options } }),
  preview: (id: string, offset = 0, limit = 100) => request<Preview>(`/datasets/${id}/preview?offset=${offset}&limit=${limit}`),
  profile: (id: string) => request<ProfileResponse>(`/datasets/${id}/profile`),
  refreshProfile: (id: string) => request<ProfileResponse>(`/datasets/${id}/profile`, { method: "POST" }),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  execute: (sql: string, offset = 0, limit = 100, extra: { saved_query_id?: string; record_history?: boolean } = {}) =>
    request<QueryResult>(`/queries/execute`, { method: "POST", json: { sql, offset, limit, ...extra } }),
  explain: (sql: string) => request<{ plan: string }>(`/queries/explain`, { method: "POST", json: { sql } }),
  savedQueries: () => request<Page<SavedQuery>>(`/queries?limit=200`),
  createSavedQuery: (body: { name: string; sql: string; description?: string }) => request<SavedQuery>(`/queries`, { method: "POST", json: body }),
  updateSavedQuery: (id: string, body: Partial<{ name: string; sql: string; description: string }>) =>
    request<SavedQuery>(`/queries/${id}`, { method: "PATCH", json: body }),
  deleteSavedQuery: (id: string) => request<void>(`/queries/${id}`, { method: "DELETE" }),
  history: (offset = 0) => request<Page<QueryRun>>(`/queries/history?limit=50&offset=${offset}`),
  transformations: (datasetId?: string) => request<Transformation[]>(`/transformations${datasetId ? `?dataset_id=${datasetId}` : ""}`),
  previewTransform: (datasetId: string, steps: TransformStep[], offset = 0, limit = 100) =>
    request<TransformPreview>(`/transformations/preview`, { method: "POST", json: { dataset_id: datasetId, steps, offset, limit } }),
  createTransformation: (body: { dataset_id: string; name: string; steps: TransformStep[] }) =>
    request<Transformation>(`/transformations`, { method: "POST", json: body }),
  updateTransformation: (id: string, body: { name?: string; steps?: TransformStep[] }) =>
    request<Transformation>(`/transformations/${id}`, { method: "PATCH", json: body }),
  deleteTransformation: (id: string) => request<void>(`/transformations/${id}`, { method: "DELETE" }),
  materialize: (id: string, name?: string) =>
    request<{ dataset_id: string; job_id: string }>(`/transformations/${id}/materialize`, { method: "POST", json: name ? { name } : {} }),
  settings: () => request<Record<string, unknown>>(`/settings`),

  sourceColumns: (source: ChartSource) =>
    request<{ columns: ColumnSchema[] }>(`/charts/source-columns`, { method: "POST", json: source }),
  chartPreview: (source: ChartSource, spec: ChartSpec, filters: Condition[] = []) =>
    request<ChartData>(`/charts/data`, { method: "POST", json: { ...source, spec, filters } }),
  charts: () => request<Chart[]>(`/charts`),
  chart: (id: string) => request<Chart>(`/charts/${id}`),
  createChart: (body: ChartSource & { name: string; spec: ChartSpec }) => request<Chart>(`/charts`, { method: "POST", json: body }),
  updateChart: (id: string, body: { name?: string; spec?: ChartSpec }) => request<Chart>(`/charts/${id}`, { method: "PATCH", json: body }),
  deleteChart: (id: string) => request<void>(`/charts/${id}`, { method: "DELETE" }),
  chartData: (id: string, filters: Condition[] = []) =>
    request<ChartData>(`/charts/${id}/data`, { method: "POST", json: { filters } }),

  dashboards: () => request<Page<Dashboard>>(`/dashboards?limit=200`),
  dashboard: (id: string) => request<Dashboard>(`/dashboards/${id}`),
  createDashboard: (body: { name: string; description?: string; layout?: LayoutItem[] }) =>
    request<Dashboard>(`/dashboards`, { method: "POST", json: body }),
  updateDashboard: (id: string, body: Partial<Pick<Dashboard, "name" | "description" | "layout" | "filters">>) =>
    request<Dashboard>(`/dashboards/${id}`, { method: "PATCH", json: body }),
  deleteDashboard: (id: string) => request<void>(`/dashboards/${id}`, { method: "DELETE" }),

  createExport: (source: ExportSource, format: "csv" | "parquet") =>
    request<ExportRecord>(`/exports`, { method: "POST", json: { source, format } }),
  getExport: (id: string) => request<ExportRecord>(`/exports/${id}`),
};

export const absoluteUrl = (path: string) => `${API_URL}${path}`;
