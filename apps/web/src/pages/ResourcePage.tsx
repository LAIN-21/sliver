import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, getResource } from "../api";
import {
  formatBytes,
  formatCategory,
  formatPrice,
  formatRange,
} from "../format";
import type { CustomSliceFilter, PublicResource } from "../types";
import "../components/ProductPages.css";

type State =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "error" }
  | { kind: "ready"; resource: PublicResource };

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
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        setState(
          error instanceof ApiError && error.status === 404
            ? { kind: "missing" }
            : { kind: "error" },
        );
      });
    return () => controller.abort();
  }, [id]);

  if (state.kind === "loading") return <ResourceLoading />;
  if (state.kind === "missing")
    return <Back message="This Resource is not published." />;
  if (state.kind === "error")
    return <Back message="The listing could not be loaded." />;
  const { resource } = state;
  const time = resource.coverage.time;

  return (
    <article className="resource-page">
      <div className="resource-page__sheet">
        <Link to="/" className="resource-page__back">
          ← Marketplace
        </Link>
        <header className="resource-page__header">
          <p className="resource-page__eyebrow">
            Resource / {formatCategory(resource.category)}
          </p>
          <h1>{resource.title}</h1>
          <p className="resource-page__seller">
            Published by <span>{resource.seller.name}</span>
          </p>
          <p className="resource-page__description">{resource.description}</p>
        </header>
        {resource.derived_from ? (
          <p className="resource-page__slice-note">
            A custom slice an agent asked for:{" "}
            {describeFilter(resource.derived_from.filter)}. Cut from{" "}
            <Link
              to={`/resources/${resource.derived_from.id}`}
              className="font-medium text-brand hover:underline"
            >
              the full dataset
            </Link>{" "}
            and priced per row. It is not listed in search.
          </p>
        ) : null}

        <dl className="resource-page__facts">
          <Fact
            label="Rows"
            value={resource.row_count.toLocaleString("en-US")}
          />
          <Fact
            label="Format"
            value={`CSV · ${formatBytes(resource.content.size_bytes)}`}
          />
          {time ? (
            <Fact
              label={`Coverage (${time.column})`}
              value={formatRange(time.start, time.end)}
            />
          ) : null}
          {resource.derived_from ? (
            <Fact label="Slice" value="Custom slice" />
          ) : resource.coverage.slice ? (
            <Fact
              label={`Slice (${resource.coverage.slice.column})`}
              value={resource.coverage.slice.value}
            />
          ) : (
            <Fact label="Slice" value="Full dataset" />
          )}
        </dl>

        <section
          className="resource-page__section"
          aria-labelledby="resource-columns"
        >
          <div className="resource-page__section-heading">
            <h2 id="resource-columns">Columns</h2>
            <span>{resource.columns.length} fields</span>
          </div>
          <div
            className="resource-page__table-wrap"
            tabIndex={0}
            role="region"
            aria-label="Column schema"
          >
            <table className="resource-page__table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Type</th>
                </tr>
              </thead>
              <tbody>
                {resource.columns.map((column) => (
                  <tr key={column.name}>
                    <td className="resource-page__column-name">
                      {column.name}
                    </td>
                    <td>
                      <span className="resource-page__column-type">
                        {column.type}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section
          className="resource-page__section"
          aria-labelledby="resource-provenance"
        >
          <div className="resource-page__section-heading">
            <h2 id="resource-provenance">Provenance & integrity</h2>
          </div>
          <dl className="resource-page__provenance">
            <Fact
              label="Provenance"
              value={[resource.provenance.source, resource.provenance.method]
                .filter(Boolean)
                .join(". ")}
            />
            <Fact
              label="Content SHA-256"
              value={resource.content.sha256}
              mono
            />
          </dl>
        </section>
        {resource.sample_rows.length ? (
          <section
            className="resource-page__section"
            aria-labelledby="resource-samples"
          >
            <div className="resource-page__section-heading">
              <h2 id="resource-samples">Sample rows</h2>
              <span>Seller selected</span>
            </div>
            <p className="resource-page__section-copy">
              The seller chose to show{" "}
              {resource.sample_rows.length === 1
                ? "this row"
                : `these ${resource.sample_rows.length} rows`}{" "}
              publicly. The rest is delivered after payment.
            </p>
            <div
              className="resource-page__table-wrap resource-page__table-wrap--samples"
              tabIndex={0}
              role="region"
              aria-label="Public sample rows"
            >
              <table className="resource-page__table">
                <thead>
                  <tr>
                    {resource.columns.map((column) => (
                      <th
                        key={column.name}
                        scope="col"
                        className="resource-page__column-name"
                      >
                        {column.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {resource.sample_rows.map((row, index) => (
                    <tr key={index}>
                      {row.map((cell, position) => (
                        <td key={position}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}
        <p className="resource-page__privacy-note">
          Listings never include the data itself, except sample rows a seller
          chose to make public; it is delivered after payment.
        </p>
      </div>

      <aside
        className="resource-purchase"
        aria-label="Agent purchase instructions"
      >
        <p className="resource-purchase__eyebrow">Price per purchase</p>
        <p className="resource-purchase__price">
          {formatPrice(resource.price.amount_minor)}
        </p>
        <p className="resource-purchase__network">x402 · XRP Ledger Testnet</p>
        <div className="resource-purchase__instructions">
          <span className="resource-purchase__step">01 / Connect</span>
          <h2>Buy with your agent</h2>
          <p>
            Agents pay per request with x402 on the XRP Ledger Testnet, to
            Sliver, which pays the seller. The free Sliver MCP lets any agent
            search, check fit and buy within your budget.
          </p>
          <pre tabIndex={0} aria-label="Sliver MCP installation command">
            {MCP_INSTALL}
          </pre>
        </div>
        {resource.custom_slices.available ? (
          <div className="resource-purchase__custom">
            <span className="resource-purchase__step">02 / Refine</span>
            <p>
              <strong>Custom slices available.</strong> Need only some rows?
              Your agent can quote a slice of this dataset by date range or
              category with <code>sliver_quote_slice</code>, priced per row and
              never above this price. Quoting is free.
            </p>
          </div>
        ) : null}
        <p className="resource-purchase__id">
          Resource ID <span>{resource.id}</span>
        </p>
      </aside>
    </article>
  );
}

function describeFilter(filter: CustomSliceFilter): string {
  const parts: string[] = [];
  if (filter.time) {
    const { column, start, end } = filter.time;
    parts.push(
      start && end
        ? `${column} ${start} to ${end}`
        : start
          ? `${column} from ${start}`
          : `${column} until ${end}`,
    );
  }
  for (const [column, value] of Object.entries(filter.where ?? {}))
    parts.push(`${column} ${value}`);
  return parts.join(", ");
}

function Fact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="resource-page__fact">
      <dt>{label}</dt>
      <dd className={mono ? "resource-page__hash" : undefined}>{value}</dd>
    </div>
  );
}

function Back({ message }: { message: string }) {
  return (
    <div className="resource-page__state">
      <p className="resource-page__eyebrow">Resource unavailable</p>
      <h1>{message}</h1>
      <Link to="/" className="resource-page__back">
        Back to the marketplace
      </Link>
    </div>
  );
}

function ResourceLoading() {
  return (
    <div
      className="resource-page resource-page--loading"
      role="status"
      aria-label="Loading resource"
    >
      <div className="resource-page__sheet">
        <p className="resource-page__eyebrow">Loading…</p>
        <div
          className="resource-page__skeleton resource-page__skeleton--title"
          aria-hidden="true"
        />
        <div
          className="resource-page__skeleton resource-page__skeleton--copy"
          aria-hidden="true"
        />
        <div
          className="resource-page__skeleton resource-page__skeleton--table"
          aria-hidden="true"
        />
      </div>
      <div className="resource-page__loading-aside" aria-hidden="true" />
    </div>
  );
}
