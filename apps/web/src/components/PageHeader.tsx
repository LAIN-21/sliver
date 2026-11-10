import type { ReactNode } from "react";

export default function PageHeader({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="workspace-page-heading">
      <p className="eyebrow">Sliver / Workspace</p>
      <h1>{title}</h1>
      {children ? <p className="workspace-description">{children}</p> : null}
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state-mark" aria-hidden="true">
        /
      </span>
      <p className="font-medium">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</p>
    </div>
  );
}
