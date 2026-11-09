import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, getResource } from "../api";
import { formatBytes, formatCategory, formatPrice, formatRange } from "../format";
import type { PublicResource } from "../types";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "error" } | { kind: "ready"; resource: PublicResource };

const MCP_INSTALL =
  'claude mcp add sliver -- uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp';

export default function ResourcePage() {
  const { id = "" } = useParams();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    getResource(id, controller.signal)
      .then((resource) => setState({ kind: "ready", resource }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState(error instanceof ApiError && error.status === 404 ? { kind: "missing" } : { kind: "error" });
      });
    return () => controller.abort();
  }, [id]);

  if (state.kind === "loading") return <p className="text-muted">Loading…</p>;
  if (state.kind === "missing") return <Back message="This Resource is not published." />;
  if (state.kind === "error") return <Back message="The listing could not be loaded." />;
  const { resource } = state;
  const time = resource.coverage.time;

  return (
    <article className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0">
        <Link to="/" className="text-sm font-medium text-brand hover:underline">
          ← Marketplace
        </Link>
        <p className="mt-4 text-sm text-muted">
          {formatCategory(resource.category)} · {resource.seller.name}
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-3xl">
          {resource.title}
        </h1>
        <p className="mt-3 text-muted">{resource.description}</p>

        <dl className="mt-6 grid gap-4 rounded-xl border border-line bg-white p-5 sm:grid-cols-2">
          <Fact label="Rows" value={resource.row_count.toLocaleString("en-US")} />
          <Fact label="Format" value={`CSV · ${formatBytes(resource.content.size_bytes)}`} />
          {time ? <Fact label={`Coverage (${time.column})`} value={formatRange(time.start, time.end)} /> : null}
          {resource.coverage.slice ? (
            <Fact label={`Slice (${resource.coverage.slice.column})`} value={resource.coverage.slice.value} />
          ) : (
            <Fact label="Slice" value="Full dataset" />
          )}
          <Fact label="Provenance" value={[resource.provenance.source, resource.provenance.method].filter(Boolean).join(". ")} />
          <Fact label="Content SHA-256" value={resource.content.sha256} mono />
        </dl>

        <h2 className="mt-8 text-lg font-semibold">Columns</h2>
        <div className="mt-3 overflow-x-auto rounded-xl border border-line bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {resource.columns.map((column) => (
                <tr key={column.name} className="border-t border-line">
                  <td className="px-4 py-2 font-mono">{column.name}</td>
                  <td className="px-4 py-2 text-muted">{column.type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-muted">Listings never include the data itself; it is delivered after payment.</p>
      </div>

      <aside className="h-fit min-w-0 rounded-xl border border-line bg-white p-5 lg:sticky lg:top-6">
        <p className="text-sm text-muted">Price per purchase</p>
        <p className="text-3xl font-semibold tabular-nums">{formatPrice(resource.price.amount_minor)}</p>
        <h2 className="mt-5 font-semibold">Buy with your agent</h2>
        <p className="mt-1 text-sm text-muted">
          Agents pay per request with x402 on the XRP Ledger Testnet, straight to the seller. The free Sliver MCP lets
          any agent search, check fit and buy within your budget.
        </p>
        <pre className="mt-3 overflow-x-auto rounded-lg bg-ink p-3 text-xs text-white">{MCP_INSTALL}</pre>
        <p className="mt-3 text-xs text-muted">
          Resource ID <span className="font-mono [overflow-wrap:anywhere]">{resource.id}</span>
        </p>
      </aside>
    </article>
  );
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
      <Link to="/" className="mt-2 inline-block font-medium text-brand hover:underline">
        Back to the marketplace
      </Link>
    </div>
  );
}
