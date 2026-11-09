import type { DatasetStatus, Finding, StepStatus, StepSummary } from "../types";

const STEP_STYLES: Record<StepStatus, string> = {
  pending: "bg-surface text-muted",
  running: "bg-brand-soft text-brand",
  passed: "bg-emerald-50 text-emerald-800",
  warning: "bg-amber-50 text-amber-800",
  failed: "bg-red-50 text-red-800",
  skipped: "bg-surface text-muted line-through",
};

const STEP_LABELS: Record<StepStatus, string> = {
  pending: "Waiting",
  running: "Running…",
  passed: "Passed",
  warning: "Warnings",
  failed: "Failed",
  skipped: "Skipped",
};

const DATASET_LABELS: Record<DatasetStatus, [string, string]> = {
  queued: ["Queued", "bg-surface text-muted"],
  inspecting: ["Inspecting…", "bg-brand-soft text-brand"],
  review: ["Ready for review", "bg-emerald-50 text-emerald-800"],
  rejected: ["Needs changes", "bg-red-50 text-red-800"],
  accepted: ["Accepted", "bg-emerald-50 text-emerald-800"],
};

const SEVERITY_STYLES: Record<Finding["severity"], string> = {
  high: "bg-red-100 text-red-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-surface text-muted",
};

export function StepPill({ status }: { status: StepStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${STEP_STYLES[status]}`}>
      {STEP_LABELS[status]}
    </span>
  );
}

export function DatasetPill({ status }: { status: DatasetStatus }) {
  const [label, style] = DATASET_LABELS[status] ?? [status, "bg-surface text-muted"];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${style}`}>{label}</span>;
}

export function SeverityBadge({ severity }: { severity: Finding["severity"] }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold uppercase ${SEVERITY_STYLES[severity]}`}>
      {severity}
    </span>
  );
}

export function inProgress(status: DatasetStatus, steps: StepSummary[]): boolean {
  return status === "queued" || status === "inspecting" || steps.some((step) => step.status === "pending" || step.status === "running");
}
