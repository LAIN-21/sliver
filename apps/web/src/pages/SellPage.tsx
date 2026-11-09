import { useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiError, listDatasets } from "../api";
import PageHeader, { EmptyState } from "../components/PageHeader";
import { DatasetPill, inProgress, StepPill } from "../components/PipelineStatus";
import RequireAccount from "../components/RequireAccount";
import { PRIMARY_BUTTON } from "../components/Form";
import { formatBytes } from "../format";
import type { Account, SellerDataset } from "../types";

const POLL_MS = 3_000;

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; items: SellerDataset[] };

export default function SellPage() {
  return <RequireAccount>{(account) => <Workspace account={account} />}</RequireAccount>;
}

function Workspace({ account }: { account: Account }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const seller = account.role === "seller";
  const busy = state.kind === "ready" && state.items.some((item) => inProgress(item.status, item.steps));

  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      listDatasets(controller.signal)
        .then((items) => setState({ kind: "ready", items }))
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setState({ kind: "error", message: error instanceof ApiError ? error.message : "Could not load datasets." });
        });
    load();
    // Keep polling only while something is still being inspected.
    const timer = busy ? window.setInterval(load, POLL_MS) : undefined;
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [busy]);

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader title={seller ? "Your datasets" : "Review queue"}>
          {seller
            ? "Every upload is validated, profiled, scanned for personal data and checked for duplicates before review."
            : "Datasets that passed automated inspection and are waiting for review."}
        </PageHeader>
        {seller ? (
          <Link to="/sell/upload" className={PRIMARY_BUTTON}>
            Upload a dataset
          </Link>
        ) : null}
      </div>
      {state.kind === "loading" ? <p className="text-muted">Loading…</p> : null}
      {state.kind === "error" ? <p className="text-red-700">{state.message}</p> : null}
      {state.kind === "ready" && state.items.length === 0 ? (
        <EmptyState title={seller ? "No uploads yet" : "Nothing to review"}>
          {seller
            ? "Upload a UTF-8 CSV of up to 5 MiB with its provenance to start the inspection pipeline."
            : "Datasets appear here once their inspection finishes without blocking issues."}
        </EmptyState>
      ) : null}
      {state.kind === "ready" && state.items.length > 0 ? (
        <ul className="space-y-3">
          {state.items.map((item) => (
            <li key={item.id}>
              <Link
                to={`/sell/datasets/${item.id}`}
                className="block rounded-xl border border-line bg-white p-4 hover:border-brand"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium [overflow-wrap:anywhere]">{item.title}</span>
                  <DatasetPill status={item.status} />
                </div>
                <p className="mt-1 text-sm text-muted">
                  {item.filename} · {formatBytes(item.size_bytes)}
                  {item.row_count ? ` · ${item.row_count.toLocaleString("en-US")} rows` : ""} · uploaded{" "}
                  {new Date(item.created_at).toLocaleString()}
                </p>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
                  {item.steps.map((step) => (
                    <span key={step.stage} className="flex items-center gap-1.5 text-sm">
                      {step.label}
                      <StepPill status={step.status} />
                    </span>
                  ))}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}
