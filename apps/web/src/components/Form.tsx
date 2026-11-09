import type { ReactNode } from "react";

export const INPUT = "w-full min-w-0 rounded-lg border border-line bg-white px-3 py-2 outline-none focus:border-brand";
export const PRIMARY_BUTTON =
  "rounded-lg bg-brand px-4 py-2 font-medium text-white hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-60";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      <div className="mt-1">{children}</div>
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
      {children}
    </p>
  );
}
