/**
 * Typed client for the Facet API. All requests go straight to the FastAPI server
 * (CORS-enabled) so large uploads stream without passing through Next.js.
 */
import type { Dataset, IngestOptions, Job, Page, Preview, QueryResult, ColumnSchema, DatasetVersion } from "./types";

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
  job: (id: string) => request<Job>(`/jobs/${id}`),
  execute: (sql: string, offset = 0, limit = 100, extra: { saved_query_id?: string; record_history?: boolean } = {}) =>
    request<QueryResult>(`/queries/execute`, { method: "POST", json: { sql, offset, limit, ...extra } }),
  explain: (sql: string) => request<{ plan: string }>(`/queries/explain`, { method: "POST", json: { sql } }),
  settings: () => request<Record<string, unknown>>(`/settings`),
};
