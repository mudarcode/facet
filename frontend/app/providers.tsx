"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Tooltip } from "radix-ui";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            refetchOnWindowFocus: false,
            retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Tooltip.Provider>{children}</Tooltip.Provider>
      <Toaster position="bottom-right" toastOptions={{ className: "!text-[13px] !rounded-lg !border-[var(--border)] !bg-[var(--surface)] !text-[var(--fg)]" }} />
    </QueryClientProvider>
  );
}
