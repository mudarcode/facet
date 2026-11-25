"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Dataset } from "@/lib/types";

const inFlight = (d: Dataset) => d.status === "pending" || d.status === "processing";

export function useDatasets() {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: () => api.listDatasets(),
    // Poll only while something is importing.
    refetchInterval: (q) => (q.state.data?.items.some(inFlight) ? 1000 : false),
  });
}

export function useDataset(id: string) {
  return useQuery({
    queryKey: ["datasets", id],
    queryFn: () => api.getDataset(id),
    refetchInterval: (q) => (q.state.data && inFlight(q.state.data) ? 1000 : false),
  });
}

export function useJob(id: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["jobs", id],
    queryFn: () => api.job(id!),
    enabled: !!id && enabled,
    refetchInterval: (q) => (q.state.data && ["succeeded", "failed", "cancelled"].includes(q.state.data.status) ? false : 700),
  });
}

export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteDataset(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
}

export function useRenameDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; sql_name?: string; description?: string }) => api.patchDataset(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
}
