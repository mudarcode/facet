import type { ReactNode } from "react";

export function PageHeader({ title, description, actions, breadcrumb }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; breadcrumb?: ReactNode }) {
  return (
    <header className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-5 py-2.5 pl-14 md:pl-5">
      <div className="min-w-0">
        {breadcrumb ? <div className="mb-0.5 text-xs text-subtle">{breadcrumb}</div> : null}
        <h1 className="truncate text-[15px] font-semibold tracking-tight">{title}</h1>
        {description ? <p className="truncate text-xs text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}
