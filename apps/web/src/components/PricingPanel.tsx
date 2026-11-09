import { useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiError, getValuation, publishDataset } from "../api";
import { formatBps, formatPrice, netAfterFee } from "../format";
import type { SellerDatasetDetail, SliverValuation, ValuationFactor, ValuationReport } from "../types";
import { ErrorMessage, INPUT, PRIMARY_BUTTON } from "./Form";

const MIN_MINOR = 1;
const MAX_MINOR = 100_000_000;

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; report: ValuationReport };

/** The seller's valuation report: breakdown, accept or override each price, optional public rows, publish. */
export default function PricingPanel({
  dataset,
  onPublished,
}: {
  dataset: SellerDatasetDetail;
  onPublished: (dataset: SellerDatasetDetail) => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  // Bumped to fetch the report again, e.g. after the suggestions changed under the seller.
  const [version, setVersion] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    getValuation(dataset.id, controller.signal)
      .then((report) => setState({ kind: "ready", report }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ kind: "error", message: error instanceof ApiError ? error.message : "The valuation could not be loaded." });
      });
    return () => controller.abort();
  }, [dataset.id, dataset.status, version]);

  function onStale(message: string) {
    setNotice(message);
    setVersion((current) => current + 1);
  }

  return (
    <section className="mt-6 rounded-xl border border-line bg-white p-5">
      <h2 className="text-lg font-semibold">{dataset.status === "published" ? "Published prices" : "Price and publish"}</h2>
      {notice ? (
        <p role="status" className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {notice} The suggestions below are current.
        </p>
      ) : null}
      {state.kind === "loading" ? <p className="mt-2 text-sm text-muted">Computing the valuation…</p> : null}
      {state.kind === "error" ? <p className="mt-2 text-sm text-red-700">{state.message}</p> : null}
      {state.kind === "ready" ? (
        state.report.publishable ? (
          <Publish report={state.report} onPublished={onPublished} onStale={onStale} />
        ) : (
          <Published report={state.report} />
        )
      ) : null}
    </section>
  );
}

function ExplanationBox({ report }: { report: ValuationReport }) {
  const explanation = report.explanation;
  if (!explanation) return null;
  const by = explanation.source === "claude" ? `Claude (${explanation.model ?? "model"})` : "Sliver's template";
  return (
    <div className="mt-3 rounded-lg bg-surface p-4">
      <p className="text-sm [overflow-wrap:anywhere]">{explanation.text}</p>
      <p className="mt-2 text-xs text-muted">
        Explained by {by}. The numbers come from Sliver's deterministic formula; the explanation never changes them.
      </p>
    </div>
  );
}

function parseDollars(text: string): number | null {
  const cleaned = text.trim().replace(/^\$/, "").replace(/,/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const [whole, cents = ""] = cleaned.split(".");
  const minor = Number(whole) * 100 + Number(cents.padEnd(2, "0"));
  return Number.isSafeInteger(minor) ? minor : null;
}

function Publish({
  report,
  onPublished,
  onStale,
}: {
  report: ValuationReport;
  onPublished: (dataset: SellerDatasetDetail) => void;
  onStale: (message: string) => void;
}) {
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<number[]>([]);
  const [allowCustom, setAllowCustom] = useState(report.custom_slices.allowed);
  const [open, setOpen] = useState<string | null>(report.slivers[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prices: Record<string, number> = {};
  const invalid: string[] = [];
  for (const [id, text] of Object.entries(overrides)) {
    if (!text.trim()) continue;
    const minor = parseDollars(text);
    if (minor === null || minor < MIN_MINOR || minor > MAX_MINOR) invalid.push(id);
    else prices[id] = minor;
  }

  function toggle(row: number) {
    setSelected((current) =>
      current.includes(row) ? current.filter((value) => value !== row) : [...current, row].sort((a, b) => a - b),
    );
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const suggested = Object.fromEntries(
        report.slivers.flatMap((sliver) => (sliver.valuation ? [[sliver.id, sliver.valuation.suggested_price_minor]] : [])),
      );
      onPublished(await publishDataset(report.dataset_id, prices, selected, suggested, allowCustom));
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        // The suggestions moved (new demand or comparables), or the dataset changed state: reload.
        onStale(failure.message);
        return;
      }
      setError(failure instanceof ApiError ? failure.message : "Could not publish.");
      setBusy(false);
    }
  }

  const full = report.slivers[0];
  return (
    <>
      <p className="mt-1 text-sm text-muted">
        Each sliver gets a suggested price from quality, uniqueness against the catalog, buyer demand, public availability
        and coverage. Accept it or type your own price, then publish. Buyers pay Sliver on the XRP Ledger Testnet; Sliver keeps
        its {formatBps(report.platform_fee.bps)} fee and pays you the rest on the 1st and 16th of each month.
      </p>
      {full?.valuation ? (
        <p className="mt-4 text-sm">
          Suggested for the full dataset:{" "}
          <span className="text-2xl font-semibold tabular-nums">{formatPrice(full.valuation.suggested_price_minor)}</span>{" "}
          <span className="text-muted">
            (range {formatPrice(full.valuation.range.low_price_minor)} to {formatPrice(full.valuation.range.high_price_minor)})
          </span>
          <br />
          <NetNote priceMinor={prices[full.id] ?? full.valuation.suggested_price_minor} bps={report.platform_fee.bps} />
        </p>
      ) : null}
      <ExplanationBox report={report} />
      {!report.payout_ready ? (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Your account has no XRPL payout address yet, so buyers cannot pay for published slivers. Run <code>make wallets</code>{" "}
          to set one.
        </p>
      ) : null}

      <div className="mt-4 overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Sliver</th>
              <th className="px-3 py-2 font-medium">Rows</th>
              <th className="px-3 py-2 font-medium">Suggested</th>
              <th className="px-3 py-2 font-medium">Range</th>
              <th className="px-3 py-2 font-medium">Your price (USD)</th>
              <th className="px-3 py-2 font-medium">You receive</th>
              <th className="px-3 py-2 font-medium">
                <span className="sr-only">Breakdown</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {report.slivers.map((sliver) => (
              <SliverRow
                key={sliver.id}
                sliver={sliver}
                value={overrides[sliver.id] ?? ""}
                price={prices[sliver.id]}
                feeBps={report.platform_fee.bps}
                invalid={invalid.includes(sliver.id)}
                open={open === sliver.id}
                onToggle={() => setOpen(open === sliver.id ? null : sliver.id)}
                onChange={(text) => setOverrides((current) => ({ ...current, [sliver.id]: text }))}
              />
            ))}
          </tbody>
        </table>
      </div>

      <SamplePicker report={report} selected={selected} onToggle={toggle} />

      <label className="mt-5 flex items-start gap-3 rounded-lg border border-line p-3 text-sm">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={allowCustom}
          onChange={(event) => setAllowCustom(event.target.checked)}
        />
        <span>
          <span className="font-medium">Allow custom slices</span>
          <span className="mt-0.5 block text-muted">
            Agents may ask for just the rows they need (a date range or one category value). Sliver cuts them from your
            full dataset and prices them per row from your full-dataset price, never above it. Buyers pay through Sliver and
            each sale is credited to you net of Sliver's fee, paid out every 15 days like any other. This choice is fixed
            once you publish.
          </span>
        </span>
      </label>

      {error ? (
        <div className="mt-4">
          <ErrorMessage>{error}</ErrorMessage>
        </div>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || invalid.length > 0}
          className={PRIMARY_BUTTON}
        >
          {busy ? "Publishing…" : `Publish ${report.slivers.length} sliver${report.slivers.length === 1 ? "" : "s"}`}
        </button>
        <span className="text-sm text-muted">
          {Object.keys(prices).length} price{Object.keys(prices).length === 1 ? "" : "s"} overridden ·{" "}
          {selected.length ? `${selected.length} sample row${selected.length === 1 ? "" : "s"} public` : "no rows public"}
        </span>
      </div>
      {invalid.length ? <p className="mt-2 text-sm text-red-700">Prices must be between $0.01 and $1,000,000.00.</p> : null}
    </>
  );
}

function SliverRow({
  sliver,
  value,
  price,
  feeBps,
  invalid,
  open,
  onToggle,
  onChange,
}: {
  sliver: SliverValuation;
  value: string;
  price: number | undefined;
  feeBps: number;
  invalid: boolean;
  open: boolean;
  onToggle: () => void;
  onChange: (text: string) => void;
}) {
  const result = sliver.valuation;
  if (!result) return null;
  const suggested = (result.suggested_price_minor / 100).toFixed(2);
  return (
    <>
      <tr className="border-t border-line">
        <td className="px-3 py-2 [overflow-wrap:anywhere]">{sliver.label}</td>
        <td className="px-3 py-2 tabular-nums">{sliver.row_count.toLocaleString("en-US")}</td>
        <td className="px-3 py-2 font-medium tabular-nums">{formatPrice(result.suggested_price_minor)}</td>
        <td className="px-3 py-2 text-muted tabular-nums whitespace-nowrap">
          {formatPrice(result.range.low_price_minor)}–{formatPrice(result.range.high_price_minor)}
        </td>
        <td className="px-3 py-2">
          <input
            inputMode="decimal"
            aria-label={`Price for ${sliver.label} in US dollars`}
            placeholder={suggested}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            className={`${INPUT} w-28 tabular-nums ${invalid ? "border-red-400" : ""}`}
          />
        </td>
        <td
          className="px-3 py-2 tabular-nums whitespace-nowrap"
          title={`After Sliver's ${formatBps(feeBps)} fee, paid out on the 1st and 16th`}
        >
          {invalid ? "—" : formatPrice(netAfterFee(price ?? result.suggested_price_minor, feeBps))}
        </td>
        <td className="px-3 py-2">
          <button type="button" onClick={onToggle} aria-expanded={open} className="text-sm font-medium text-brand hover:underline">
            {open ? "Hide" : "Why?"}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="border-t border-line bg-surface/50">
          <td colSpan={7} className="px-3 py-3">
            <Breakdown sliver={sliver} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function baseText(result: NonNullable<SliverValuation["valuation"]>): string {
  const inputs = result.base.inputs;
  if (result.base.source === "comparables") {
    return `median of ${String(inputs.comparables)} published comparable slivers in ${String(inputs.category)}`;
  }
  return `category base for ${String(inputs.category)} (${String(inputs.comparables)} comparable slivers, too few to use)`;
}

export function Breakdown({ sliver }: { sliver: SliverValuation }) {
  const result = sliver.valuation;
  if (!result) return null;
  return (
    <div className="text-sm">
      <p>
        <span className="font-medium tabular-nums">{formatPrice(result.base.price_minor)}</span>{" "}
        <span className="text-muted">starting point: {baseText(result)}</span>
      </p>
      <ul className="mt-2 space-y-1">
        {result.factors.map((factor) => (
          <FactorLine key={factor.name} factor={factor} />
        ))}
      </ul>
      <p className="mt-2">
        = <span className="font-semibold tabular-nums">{formatPrice(result.suggested_price_minor)}</span>
      </p>
    </div>
  );
}

function FactorLine({ factor }: { factor: ValuationFactor }) {
  const tone = factor.factor > 1 ? "text-emerald-700" : factor.factor < 1 ? "text-amber-800" : "text-muted";
  const queries = factor.name === "demand" ? (factor.inputs.matched_queries as { query: string; unmet_searches: number }[]) : [];
  return (
    <li className="flex flex-wrap gap-x-2">
      <span className={`w-16 shrink-0 font-mono tabular-nums ${tone}`}>×{factor.factor}</span>
      <span className="font-medium">{factor.label}</span>
      <span className="min-w-0 text-muted [overflow-wrap:anywhere]">
        {factor.reason}
        {queries.length ? ` (${queries.map((item) => `“${item.query}” ×${item.unmet_searches}`).join(", ")})` : ""}
      </span>
    </li>
  );
}

function NetNote({ priceMinor, bps }: { priceMinor: number; bps: number }) {
  return (
    <span className="text-muted">
      You receive <span className="font-medium text-ink tabular-nums">{formatPrice(netAfterFee(priceMinor, bps))}</span> after
      Sliver's {formatBps(bps)}, paid out on the 1st and 16th of each month.
    </span>
  );
}

function SamplePicker({
  report,
  selected,
  onToggle,
}: {
  report: ValuationReport;
  selected: number[];
  onToggle: (row: number) => void;
}) {
  const { header, candidates, max_rows: max } = report.sample;
  if (!candidates.length) return null;
  const full = selected.length >= max;
  return (
    <details className="mt-5 rounded-lg border border-line">
      <summary className="cursor-pointer px-4 py-3 font-medium">
        Public sample rows (optional, {selected.length} of at most {max} selected)
      </summary>
      <div className="border-t border-line px-4 py-3">
        <p className="text-sm text-muted">
          Every row stays private unless you tick it here. Ticked rows are shown on the public listing of each sliver they
          belong to. Rows holding values the privacy scan flagged cannot be made public.
        </p>
        <div className="mt-3 overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Public</th>
                <th className="px-3 py-2 font-medium">Row</th>
                {header.map((name) => (
                  <th key={name} className="px-3 py-2 font-mono font-medium">
                    {name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {candidates.map((candidate) => {
                const checked = selected.includes(candidate.row);
                const disabled = candidate.problem !== null || (full && !checked);
                return (
                  <tr key={candidate.row} className={`border-t border-line ${candidate.problem ? "text-muted" : ""}`}>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => onToggle(candidate.row)}
                        aria-label={`Make row ${candidate.row} public`}
                        title={candidate.problem ? `Row ${candidate.row} ${candidate.problem}.` : undefined}
                      />
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {candidate.row}
                      {candidate.problem ? <span className="sr-only"> cannot be public: {candidate.problem}</span> : null}
                    </td>
                    {candidate.values.map((value, index) => (
                      <td key={index} className="px-3 py-2 whitespace-nowrap">
                        {value}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}

function Published({ report }: { report: ValuationReport }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <p className="mt-1 text-sm text-muted">
        These slivers are live in the catalog. Agents buy them with x402 on the XRP Ledger Testnet and pay Sliver. Sliver
        keeps its fee (currently {formatBps(report.platform_fee.bps)}) and pays you the rest on the 1st and 16th of each
        month; see Insights for your balance.
      </p>
      <p className="mt-2 text-sm">
        Custom slices:{" "}
        {report.custom_slices.allowed ? (
          <>
            <span className="font-medium">allowed</span>
            <span className="text-muted">
              {" "}
              · {report.custom_slices.count.toLocaleString("en-US")} cut for buyers so far, priced per row from your
              full-dataset price
            </span>
          </>
        ) : (
          <span className="font-medium">not offered</span>
        )}
      </p>
      <ExplanationBox report={report} />
      {!report.payout_ready ? (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Your account has no XRPL payout address yet, so buyers cannot pay. Run <code>make wallets</code> to set one.
        </p>
      ) : null}
      <div className="mt-4 overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Sliver</th>
              <th className="px-3 py-2 font-medium">Price</th>
              <th className="px-3 py-2 font-medium">You receive</th>
              <th className="px-3 py-2 font-medium">Suggested</th>
              <th className="px-3 py-2 font-medium">Public rows</th>
              <th className="px-3 py-2 font-medium">
                <span className="sr-only">Links</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {report.slivers.map((sliver) => (
              <PublishedRow
                key={sliver.id}
                sliver={sliver}
                feeBps={report.platform_fee.bps}
                open={open === sliver.id}
                onToggle={() => setOpen(open === sliver.id ? null : sliver.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
      {report.sample.selected.length ? (
        <p className="mt-3 text-sm text-muted">Public sample rows: {report.sample.selected.join(", ")}.</p>
      ) : (
        <p className="mt-3 text-sm text-muted">No rows are public.</p>
      )}
    </>
  );
}

function PublishedRow({
  sliver,
  feeBps,
  open,
  onToggle,
}: {
  sliver: SliverValuation;
  feeBps: number;
  open: boolean;
  onToggle: () => void;
}) {
  const live = sliver.status === "published";
  return (
    <>
      <tr className="border-t border-line">
        <td className="px-3 py-2 [overflow-wrap:anywhere]">{sliver.label}</td>
        <td className="px-3 py-2 font-medium tabular-nums">{sliver.price_minor ? formatPrice(sliver.price_minor) : "—"}</td>
        <td className="px-3 py-2 tabular-nums" title={`After Sliver's current ${formatBps(feeBps)} fee, paid out on the 1st and 16th`}>
          {sliver.price_minor ? formatPrice(netAfterFee(sliver.price_minor, feeBps)) : "—"}
        </td>
        <td className="px-3 py-2 text-muted tabular-nums">
          {sliver.valuation ? formatPrice(sliver.valuation.suggested_price_minor) : "—"}
          {sliver.accepted_suggestion === false ? " (overridden)" : ""}
        </td>
        <td className="px-3 py-2 tabular-nums">{sliver.sample_rows ?? 0}</td>
        <td className="px-3 py-2 whitespace-nowrap">
          {live ? (
            <Link to={`/resources/${sliver.id}`} className="mr-3 font-medium text-brand hover:underline">
              Listing
            </Link>
          ) : null}
          {sliver.valuation ? (
            <button type="button" onClick={onToggle} aria-expanded={open} className="text-sm font-medium text-brand hover:underline">
              {open ? "Hide" : "Why?"}
            </button>
          ) : null}
        </td>
      </tr>
      {open ? (
        <tr className="border-t border-line bg-surface/50">
          <td colSpan={6} className="px-3 py-3">
            <Breakdown sliver={sliver} />
          </td>
        </tr>
      ) : null}
    </>
  );
}
