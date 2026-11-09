import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, getDataset, reviewDataset } from "../api";
import { ErrorMessage, Field, INPUT, PRIMARY_BUTTON } from "../components/Form";
import { DatasetPill, inProgress, SeverityBadge, StepPill } from "../components/PipelineStatus";
import RequireAccount from "../components/RequireAccount";
import { formatBytes, formatCategory, formatRange } from "../format";
import type {
  Account,
  AiReviewDetails,
  ColumnProfile,
  DecisionDetails,
  PackagedResource,
  ResearchSource,
  SellerDatasetDetail,
  StepDetail,
} from "../types";

const POLL_MS = 1_500;

type State =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "error"; message: string }
  | { kind: "ready"; dataset: SellerDatasetDetail };

export default function DatasetPage() {
  const { id = "" } = useParams();
  // Keyed by id so following a link to another dataset (duplicate findings) starts fresh.
  return <RequireAccount>{(account) => <DatasetView key={id} id={id} account={account} />}</RequireAccount>;
}

function DatasetView({ id, account }: { id: string; account: Account }) {
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

      <Decision
        dataset={dataset}
        account={account}
        onDecided={(updated) => setState({ kind: "ready", dataset: updated })}
      />
      <ProposedListing step={dataset.steps.find((step) => step.stage === "ai_review")} />
      {dataset.resources.length ? <Slivers resources={dataset.resources} /> : null}

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
      {step.stage === "decide" && step.details.decision ? <Score details={step.details as DecisionDetails} /> : null}
      {step.stage === "research" && Array.isArray(step.details.sources) ? (
        <Sources sources={step.details.sources as ResearchSource[]} />
      ) : null}
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

function Decision({
  dataset,
  account,
  onDecided,
}: {
  dataset: SellerDatasetDetail;
  account: Account;
  onDecided: (dataset: SellerDatasetDetail) => void;
}) {
  if (dataset.review) {
    const approved = dataset.review.decision === "approved";
    return (
      <section className={`mt-6 rounded-xl border p-5 ${approved ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`}>
        <h2 className="font-semibold">{approved ? "Approved by a reviewer" : "Rejected by a reviewer"}</h2>
        <p className="mt-1 text-sm [overflow-wrap:anywhere]">{dataset.review.reason}</p>
        <p className="mt-2 text-xs text-muted">
          {dataset.review.reviewer ?? "Reviewer"} · {new Date(dataset.review.decided_at).toLocaleString()}
        </p>
      </section>
    );
  }
  if (dataset.status === "accepted") {
    return (
      <section className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
        <h2 className="font-semibold">Accepted automatically</h2>
        <p className="mt-1 text-sm">No blocking findings and the quality score cleared the threshold. The slivers are ready for pricing.</p>
      </section>
    );
  }
  if (dataset.status !== "review") return null;
  if (account.role !== "reviewer") {
    return (
      <section className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h2 className="font-semibold">Waiting for a reviewer</h2>
        <p className="mt-1 text-sm">The acceptance decision below explains why this dataset needs a human.</p>
      </section>
    );
  }
  return <ReviewForm datasetId={dataset.id} onDecided={onDecided} />;
}

function ReviewForm({ datasetId, onDecided }: { datasetId: string; onDecided: (dataset: SellerDatasetDetail) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    // Only a click on one of the two buttons records a decision; never assume an approval.
    const decision = submitter?.value;
    if (decision !== "approve" && decision !== "reject") {
      setError("Choose Approve or Reject.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onDecided(await reviewDataset(datasetId, decision, reason));
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Could not record the decision.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-6 space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-5">
      <h2 className="font-semibold">Review this dataset</h2>
      <Field label="Reason" hint="Shown to the seller. At least 3 characters.">
        <textarea
          required
          minLength={3}
          maxLength={1000}
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className={INPUT}
        />
      </Field>
      {error ? <ErrorMessage>{error}</ErrorMessage> : null}
      <div className="flex flex-wrap gap-3">
        <button type="submit" name="decision" value="approve" disabled={busy} className={PRIMARY_BUTTON}>
          Approve
        </button>
        <button
          type="submit"
          name="decision"
          value="reject"
          disabled={busy}
          className="rounded-lg border border-red-300 bg-white px-4 py-2 font-medium text-red-800 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Reject
        </button>
      </div>
    </form>
  );
}

function ProposedListing({ step }: { step: StepDetail | undefined }) {
  const details = step?.details as AiReviewDetails | undefined;
  if (!details?.listing) return null;
  const { listing, slice } = details;
  const engine = details.engine === "claude" ? `Claude (${details.model ?? "model"}${details.cached ? ", cached" : ""})` : "offline fallback";
  return (
    <section className="mt-6 rounded-xl border border-line bg-white p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">Proposed public listing</h2>
        <span className="text-xs text-muted">Written by {engine}</span>
      </div>
      <p className="mt-3 font-medium [overflow-wrap:anywhere]">{listing.title}</p>
      <p className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">{listing.description}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-brand-soft px-2 py-0.5 font-medium text-brand">{formatCategory(listing.category)}</span>
        {listing.tags.map((tag) => (
          <span key={tag} className="rounded-full bg-surface px-2 py-0.5 text-muted">
            {tag}
          </span>
        ))}
      </div>
      {slice ? (
        <p className="mt-3 text-sm">
          Slices:{" "}
          <span className="font-medium">
            {slice.column ? (slice.period === "month" ? `${slice.column} by calendar month` : `one per ${slice.column}`) : "none"}
          </span>
          {slice.source === "rule" ? <span className="text-muted"> (chosen by Sliver's rules)</span> : null}
        </p>
      ) : null}
    </section>
  );
}

function Slivers({ resources }: { resources: PackagedResource[] }) {
  return (
    <section className="mt-6">
      <h2 className="text-lg font-semibold">Packaged slivers ({resources.length})</h2>
      <p className="mt-1 text-sm text-muted">
        Each is its own immutable CSV object. They stay private drafts until pricing and publication.
      </p>
      <div className="mt-3 overflow-x-auto rounded-lg border border-line bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Sliver</th>
              <th className="px-3 py-2 font-medium">Rows</th>
              <th className="px-3 py-2 font-medium">Size</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">SHA-256</th>
            </tr>
          </thead>
          <tbody>
            {resources.map((resource) => (
              <tr key={resource.id} className="border-t border-line">
                <td className="px-3 py-2 [overflow-wrap:anywhere]">{resource.slice ? resource.slice.value : "Full dataset"}</td>
                <td className="px-3 py-2 tabular-nums">{resource.row_count.toLocaleString("en-US")}</td>
                <td className="px-3 py-2 tabular-nums">{formatBytes(resource.size_bytes)}</td>
                <td className="px-3 py-2 text-muted">{resource.status}</td>
                <td className="px-3 py-2 font-mono text-xs" title={resource.sha256}>
                  {resource.sha256.slice(0, 12)}…
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Score({ details }: { details: DecisionDetails }) {
  return (
    <div className="mt-3 space-y-2 text-sm">
      <p>
        Quality score <span className="font-medium tabular-nums">{details.quality_score}</span> (auto-accept at{" "}
        {details.threshold})
      </p>
      {details.blocking.length ? (
        <div>
          <p className="font-medium">Needs a reviewer because:</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {details.blocking.map((item, index) => (
              <li key={`${item.stage}-${item.code}-${index}`} className="[overflow-wrap:anywhere]">
                {item.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {details.deductions.length ? (
        <ul className="list-disc space-y-1 pl-5 text-muted">
          {details.deductions.map((item, index) => (
            <li key={`${item.stage}-${item.code}-${index}`} className="[overflow-wrap:anywhere]">
              −{item.points}: {item.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Sources({ sources }: { sources: ResearchSource[] }) {
  if (!sources.length) return null;
  return (
    <ul className="mt-3 space-y-1 text-sm">
      {sources.map((source) => (
        <li key={source.url} className="[overflow-wrap:anywhere]">
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-brand hover:underline">
            {source.title || source.url}
          </a>
          {source.note ? <span className="text-muted"> — {source.note}</span> : null}
        </li>
      ))}
    </ul>
  );
}
