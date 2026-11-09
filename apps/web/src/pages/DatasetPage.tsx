import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, getDataset } from "../api";
import { DatasetPill, inProgress, SeverityBadge, StepPill } from "../components/PipelineStatus";
import RequireAccount from "../components/RequireAccount";
import { formatBytes, formatRange } from "../format";
import type { ColumnProfile, SellerDatasetDetail, StepDetail } from "../types";

const POLL_MS = 1_500;

type State =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "error"; message: string }
  | { kind: "ready"; dataset: SellerDatasetDetail };

export default function DatasetPage() {
  const { id = "" } = useParams();
  // Keyed by id so following a link to another dataset (duplicate findings) starts fresh.
  return <RequireAccount>{() => <DatasetView key={id} id={id} />}</RequireAccount>;
}

function DatasetView({ id }: { id: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const live = state.kind === "loading" || (state.kind === "ready" && inProgress(state.dataset.status, state.dataset.steps));

  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const load = () =>
      getDataset(id, controller.signal)
        .then((dataset) => {
          setState({ kind: "ready", dataset });
          if (inProgress(dataset.status, dataset.steps)) timer = window.setTimeout(load, POLL_MS);
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          if (error instanceof ApiError && error.status === 404) setState({ kind: "missing" });
          else setState({ kind: "error", message: error instanceof ApiError ? error.message : "Could not load." });
        });
    load();
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [id, live]);

  if (state.kind === "loading") return <p className="text-muted">Loading…</p>;
  if (state.kind === "missing") return <Back message="This dataset does not exist or is not visible to you." />;
  if (state.kind === "error") return <Back message={state.message} />;
  const { dataset } = state;

  return (
    <article className="min-w-0">
      <Link to="/sell" className="text-sm font-medium text-brand hover:underline">
        ← Datasets
      </Link>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-3xl">{dataset.title}</h1>
        <DatasetPill status={dataset.status} />
      </div>
      <p className="mt-2 text-sm text-muted">
        {dataset.seller.name} · {dataset.filename} · {formatBytes(dataset.size_bytes)}
        {dataset.row_count ? ` · ${dataset.row_count.toLocaleString("en-US")} rows` : ""}
      </p>

      <dl className="mt-6 grid gap-4 rounded-xl border border-line bg-white p-5 sm:grid-cols-2">
        <Fact label="Source" value={dataset.provenance.source} />
        <Fact label="Method" value={dataset.provenance.method} />
        <Fact label="Collected" value={dataset.provenance.collected_at} />
        <Fact
          label="Rights"
          value={dataset.provenance.rights_statement ?? (dataset.provenance.rights_confirmed ? "Confirmed by the seller" : "—")}
        />
        <div className="sm:col-span-2">
          <Fact label="Stored object SHA-256 (immutable)" value={dataset.sha256} mono />
        </div>
      </dl>

      <h2 className="mt-8 text-lg font-semibold">Inspection pipeline</h2>
      <ol className="mt-3 space-y-3">
        {dataset.steps.map((step, index) => (
          <Step key={step.stage} step={step} index={index + 1} />
        ))}
      </ol>
    </article>
  );
}

function Step({ step, index }: { step: StepDetail; index: number }) {
  const columns = step.stage === "profile" ? (step.details.columns as ColumnProfile[] | undefined) : undefined;
  const coverage = step.details.time_coverage as { column: string; start: string; end: string } | null | undefined;
  return (
    <li className="rounded-xl border border-line bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          {index}. {step.label}
        </span>
        <StepPill status={step.status} />
      </div>
      {step.summary ? <p className="mt-1 text-sm text-muted">{step.summary}</p> : null}
      {step.findings.length ? (
        <ul className="mt-3 space-y-2">
          {step.findings.map((finding, position) => (
            <li key={`${finding.code}-${finding.column ?? ""}-${position}`} className="flex items-start gap-2 text-sm">
              <SeverityBadge severity={finding.severity} />
              <span className="[overflow-wrap:anywhere]">
                {finding.message}
                {finding.matched_dataset ? (
                  <>
                    {" "}
                    <Link to={`/sell/datasets/${finding.matched_dataset}`} className="text-brand hover:underline">
                      Open it
                    </Link>
                  </>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {coverage ? (
        <p className="mt-3 text-sm">
          Time coverage ({coverage.column}): <span className="font-medium">{formatRange(coverage.start, coverage.end)}</span>
        </p>
      ) : null}
      {columns?.length ? <ProfileTable columns={columns} /> : null}
    </li>
  );
}

function ProfileTable({ columns }: { columns: ColumnProfile[] }) {
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">Column</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Empty</th>
            <th className="px-3 py-2 font-medium">Distinct</th>
            <th className="px-3 py-2 font-medium">Range</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((column) => (
            <tr key={column.name} className="border-t border-line">
              <td className="px-3 py-2 font-mono">{column.name}</td>
              <td className="px-3 py-2 text-muted">{column.type}</td>
              <td className="px-3 py-2 tabular-nums">{column.null_pct}%</td>
              <td className="px-3 py-2 tabular-nums">{column.distinct.toLocaleString("en-US")}</td>
              <td className="px-3 py-2 text-muted tabular-nums">{range(column)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function range(column: ColumnProfile): string {
  if (column.min !== undefined && column.max !== undefined) return formatRange(String(column.min), String(column.max));
  if (column.min_length !== undefined) return `${column.min_length}–${column.max_length} chars`;
  return "—";
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={`mt-0.5 font-medium [overflow-wrap:anywhere] ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}

function Back({ message }: { message: string }) {
  return (
    <div>
      <p className="text-muted">{message}</p>
      <Link to="/sell" className="mt-2 inline-block font-medium text-brand hover:underline">
        Back to datasets
      </Link>
    </div>
  );
}
