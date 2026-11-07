import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, downloadBytes, request } from "./api";
import { analyzeCsv, parseUsd, usd } from "./buyerAnalysis";
import type { Analysis } from "./buyerAnalysis";
import type { Marketplace, PublicResource, Quote } from "./types";

const QUOTE_KEY = "sliver-buyer-quote";
export function clearBuyerRecovery() {
  try {
    sessionStorage.removeItem(QUOTE_KEY);
  } catch {
    // Browser storage may be disabled; session revocation must still finish.
  }
}

function Failure({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="error-message" role="alert">
      {error instanceof Error
        ? error.message
        : "The request could not be completed."}
      {error instanceof ApiError && error.issues.length > 0 && (
        <ul>
          {error.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function paymentLabel(marketplace: Marketplace | null): string {
  if (marketplace?.mode === "simulated") return "SIMULATED / NO REAL MONEY";
  if (marketplace?.mode === "xrpl-testnet")
    return "XRPL TESTNET / TEST XRP ONLY";
  return "PAYMENTS DISABLED";
}

export default function BuyerWorkspace({
  marketplace,
}: {
  marketplace: Marketplace | null;
}) {
  const [items, setItems] = useState<PublicResource[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [maximum, setMaximum] = useState("");
  const [budget, setBudget] = useState("5.00");
  const [buyerAddress, setBuyerAddress] = useState("");
  const [selected, setSelected] = useState<PublicResource | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [hash, setHash] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [catalogError, setCatalogError] = useState<unknown>(null);
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [recoveryId, setRecoveryId] = useState("");
  const [now, setNow] = useState(Date.now());
  const controller = useRef(new AbortController());
  const requestSequence = useRef(0);
  const blobUrl = useRef("");
  const signal = () => controller.current.signal;

  function saveQuote(value: Quote) {
    setQuote(value);
    try {
      sessionStorage.setItem(QUOTE_KEY, value.id);
    } catch {
      // Purchases remain usable in this view if storage is unavailable.
    }
    if (value.transaction_hash) setHash(value.transaction_hash);
  }

  async function recoverQuote(id: string) {
    const activeSignal = signal();
    setRecoveryId(id);
    setBusy("Recovering session quote…");
    setError(null);
    try {
      const value = await request<Quote>(`/quotes/${encodeURIComponent(id)}`, {
        signal: activeSignal,
      });
      if (!activeSignal.aborted) {
        saveQuote(value);
        setRecoveryId("");
      }
    } catch (failure) {
      if (activeSignal.aborted) return;
      if (
        failure instanceof ApiError &&
        [401, 403, 404].includes(failure.status)
      ) {
        clearBuyerRecovery();
        setRecoveryId("");
      }
      setError(failure);
    } finally {
      if (!activeSignal.aborted) setBusy("");
    }
  }

  async function loadCatalog(q = search, max = maximum) {
    const sequence = ++requestSequence.current;
    setCatalogError(null);
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (q.trim()) params.set("q", q.trim());
      if (max.trim()) {
        const cents = parseUsd(max);
        if (cents === null)
          throw new Error(
            "Maximum price must be non-negative USD with at most two decimal places.",
          );
        params.set("max_price_minor", String(cents));
      }
      const result = await request<{ items: PublicResource[]; total: number }>(
        `/catalog?${params}`,
        { signal: signal() },
      );
      if (signal().aborted || sequence !== requestSequence.current) return;
      setItems(result.items);
      setTotal(result.total);
    } catch (failure) {
      if (!signal().aborted && sequence === requestSequence.current)
        setCatalogError(failure);
    } finally {
      if (!signal().aborted && sequence === requestSequence.current)
        setLoading(false);
    }
  }

  useEffect(() => {
    controller.current = new AbortController();
    const active = controller.current;
    void loadCatalog("", "");
    let saved: string | null = null;
    try {
      saved = sessionStorage.getItem(QUOTE_KEY);
    } catch {
      /* Optional reload recovery. */
    }
    if (saved && /^[a-zA-Z0-9-]{16,64}$/.test(saved)) {
      void recoverQuote(saved);
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      active.abort();
      window.clearInterval(timer);
      if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
    };
    // The workspace is remounted when its browser session changes.
  }, []);

  const budgetCents = parseUsd(budget);
  const price = quote?.price_minor ?? selected?.price_minor;
  const budgetReason =
    budgetCents === null
      ? "Buyer policy refuses: enter a non-negative USD budget with at most two decimal places."
      : price !== undefined && (!Number.isSafeInteger(price) || price < 0)
        ? "Buyer policy refuses: the offer has an invalid price."
        : price !== undefined && price > budgetCents
          ? `Buyer policy refuses: ${usd(price)} exceeds your ${usd(budgetCents)} budget. No quote or payment will be requested.`
          : "";
  const expired = quote ? Date.parse(quote.expires_at) <= now : false;
  const stage = analysis
    ? 4
    : quote?.status === "paid"
      ? 3
      : quote
        ? 2
        : selected
          ? 1
          : 0;

  function choose(item: PublicResource) {
    if (busy || quote?.status === "pending") return;
    setSelected(item);
    setQuote(null);
    setHash("");
    setError(null);
    setAnalysis(null);
    setCopied(false);
    setRecoveryId("");
    clearBuyerRecovery();
    if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
    blobUrl.current = "";
    setDownloadUrl("");
  }

  async function obtainQuote() {
    setError(null);
    if (!selected || budgetReason) {
      if (!budgetReason) setError(new Error("Choose a Resource first."));
      return;
    }
    if (!marketplace || marketplace.mode === "disabled") {
      setError(new Error("Purchasing is disabled in this marketplace."));
      return;
    }
    if (
      marketplace.mode === "xrpl-testnet" &&
      !/^r[1-9A-HJ-NP-Za-km-z]{24,34}$/.test(buyerAddress.trim())
    ) {
      setError(
        new Error(
          "Enter the classic XRPL testnet address that will send this payment.",
        ),
      );
      return;
    }
    setBusy("Requesting immutable quote…");
    try {
      const value = await request<Quote>("/quotes", {
        method: "POST",
        signal: signal(),
        body: JSON.stringify({
          resource_id: selected.id,
          ...(marketplace.mode === "xrpl-testnet"
            ? { buyer_address: buyerAddress.trim() }
            : {}),
        }),
      });
      if (!signal().aborted) saveQuote(value);
    } catch (failure) {
      if (!signal().aborted) setError(failure);
    } finally {
      if (!signal().aborted) setBusy("");
    }
  }

  async function confirm() {
    setError(null);
    if (!quote) return;
    if (budgetReason) {
      return;
    }
    if (quote.mode !== marketplace?.mode || quote.mode === "disabled") {
      setError(new Error("Marketplace mode changed. Request a new quote."));
      return;
    }
    if (expired && !quote.transaction_hash && quote.status !== "pending") {
      setError(
        new Error(
          "This quote expired. Choose the Resource again to request a new quote.",
        ),
      );
      return;
    }
    const transactionHash = quote.transaction_hash ?? hash.trim();
    if (
      quote.mode === "xrpl-testnet" &&
      !/^[a-fA-F0-9]{64}$/.test(transactionHash)
    ) {
      setError(
        new Error("Paste the real 64-character testnet transaction hash."),
      );
      return;
    }
    // Retain an uncertain submitted proof even if the response and recovery both fail.
    // A retry must reconcile this payment; it must never invite another transfer.
    if (quote.mode === "xrpl-testnet")
      saveQuote({
        ...quote,
        transaction_hash: transactionHash,
        status: "pending",
      });
    setBusy(
      quote.mode === "simulated"
        ? "Recording simulated purchase…"
        : "Checking validated testnet payment…",
    );
    try {
      const value = await request<Quote>(`/quotes/${quote.id}/confirm`, {
        method: "POST",
        signal: signal(),
        body: JSON.stringify(
          quote.mode === "simulated"
            ? {}
            : { transaction_hash: transactionHash },
        ),
      });
      if (!signal().aborted) saveQuote(value);
    } catch (failure) {
      if (!signal().aborted) {
        setError(failure);
        // A network error can conceal a successful mutation: recover server state before any retry.
        try {
          const value = await request<Quote>(`/quotes/${quote.id}`, {
            signal: signal(),
          });
          if (!signal().aborted) saveQuote(value);
        } catch {
          /* Keep the original actionable error. */
        }
      }
    } finally {
      if (!signal().aborted) setBusy("");
    }
  }

  async function deliver() {
    if (!quote || quote.status !== "paid") return;
    setError(null);
    setBusy("Downloading exact bytes and checking SHA-256…");
    try {
      const bytes = await downloadBytes(
        `/quotes/${quote.id}/download`,
        signal(),
      );
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const hex = Array.from(new Uint8Array(digest), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("");
      if (hex !== quote.sha256 || bytes.byteLength !== quote.size_bytes)
        throw new Error(
          "Integrity check failed. Download was withheld because SHA-256 or byte length differs from the quote.",
        );
      if (signal().aborted) return;
      if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
      blobUrl.current = URL.createObjectURL(
        new Blob([bytes], { type: "text/csv;charset=utf-8" }),
      );
      setDownloadUrl(blobUrl.current);
      setAnalysis(analyzeCsv(bytes));
    } catch (failure) {
      if (!signal().aborted) setError(failure);
    } finally {
      if (!signal().aborted) setBusy("");
    }
  }

  async function copyEvidence() {
    if (!quote) return;
    try {
      await navigator.clipboard.writeText(
        JSON.stringify(
          {
            ...quote,
            verification: downloadUrl
              ? "SHA-256 and exact byte length verified in browser"
              : "Not yet downloaded",
            analysis,
          },
          null,
          2,
        ),
      );
      setCopied(true);
    } catch {
      setError(
        new Error(
          "Clipboard unavailable. Select and copy the visible receipt evidence below.",
        ),
      );
    }
  }

  return (
    <section className="buyer-workspace" aria-labelledby="buyer-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Buyer lab / client-owned decisions</p>
          <h1 id="buyer-title">From source to a checked answer.</h1>
          <p className="intro">
            Choose a reviewed Resource, set your budget, then explicitly approve
            one purchase. Analysis runs here in your browser.
          </p>
        </div>
        <div className="buyer-mode">
          <strong>{paymentLabel(marketplace)}</strong>
          <span>
            {marketplace?.price_note ||
              "Marketplace configuration unavailable."}
          </span>
        </div>
      </div>
      <ol className="buyer-stages" aria-label="Buyer progress">
        {[
          "Discover",
          "Budget & choose",
          "Quote & confirm",
          "Receipt & delivery",
          "Checked answer",
        ].map((label, i) => (
          <li
            key={label}
            className={i <= stage ? "reached" : ""}
            aria-current={stage === i ? "step" : undefined}
          >
            <span>{String(i + 1).padStart(2, "0")}</span>
            {label}
          </li>
        ))}
      </ol>
      <div className="buyer-grid">
        <div className="buyer-discovery">
          <form
            className="buyer-filters"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              void loadCatalog();
            }}
          >
            <label className="field">
              Search catalog
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Routes, port, logistics…"
                maxLength={200}
              />
            </label>
            <label className="field">
              Maximum price (USD)
              <input
                value={maximum}
                onChange={(event) => setMaximum(event.target.value)}
                inputMode="decimal"
                placeholder="Any price"
              />
            </label>
            <button type="submit" className="button secondary">
              Filter Resources
            </button>
          </form>
          <Failure error={catalogError} />
          <div className="section-heading">
            <h2>Reviewed offers</h2>
            <span className="count-label">
              {items.length} of {total} · metadata only
            </span>
          </div>
          {loading ? (
            <p role="status">Loading catalog metadata…</p>
          ) : items.length === 0 ? (
            <div className="empty-state compact">
              <h2>No matching Resources.</h2>
              <p>
                Adjust the filters, or publish a reviewed offer from the seller
                workspace.
              </p>
            </div>
          ) : (
            items.map((item) => (
              <article
                className={`buyer-offer ${selected?.id === item.id ? "selected" : ""}`}
                key={item.id}
                aria-label={`Resource ${item.title}`}
              >
                <div className="resource-topline">
                  <span className="badge approved">
                    Reviewed for publication
                  </span>
                  <span className="mono">Version {item.dataset_version}</span>
                </div>
                <div className="buyer-offer-heading">
                  <h3>{item.title}</h3>
                  <strong>{usd(item.price_minor)}</strong>
                </div>
                <p className="resource-description">{item.description}</p>
                <p className="buyer-source">
                  Source: {item.provenance.source}
                  <br />
                  Coverage: {item.provenance.coverage}
                </p>
                <div className="data-facts">
                  <span>{item.row_count.toLocaleString()} rows</span>
                  <span>{item.size_bytes.toLocaleString()} bytes</span>
                  <span>Whole immutable CSV</span>
                </div>
                <details>
                  <summary>Schema, provenance and digest</summary>
                  <div className="column-list">
                    {item.columns.map((column) => (
                      <code key={column}>{column}</code>
                    ))}
                  </div>
                  <p className="fine-print">
                    Method: {item.provenance.method} · Collected:{" "}
                    {item.provenance.collected_at}
                  </p>
                  <code className="fingerprint">SHA-256 {item.sha256}</code>
                  <p className="fine-print">
                    Review does not certify factual accuracy or ownership.
                    Dataset rows remain private until delivery.
                  </p>
                </details>
                <button
                  className="button secondary"
                  disabled={Boolean(busy) || quote?.status === "pending"}
                  onClick={() => choose(item)}
                >
                  {selected?.id === item.id && !quote
                    ? "Selected · choose again"
                    : "Choose Resource"}
                </button>
              </article>
            ))
          )}
          {total > items.length && (
            <p className="fine-print">
              Showing the first 100 matching offers. Narrow the search to
              compare the remaining offers.
            </p>
          )}
        </div>
        <aside
          className="buyer-decision panel"
          aria-label="Buyer decision and receipt"
        >
          <div className="panel-heading">
            <span className="step-number">02</span>
            <div>
              <h2>Your purchase decision</h2>
              <p>A local client policy; Sliver does not spend autonomously.</p>
            </div>
          </div>
          <label className="field">
            Buyer budget (USD)
            <input
              value={budget}
              onChange={(event) => {
                setBudget(event.target.value);
                setError(null);
              }}
              inputMode="decimal"
              disabled={Boolean(busy)}
              aria-describedby="budget-note"
            />
            <small id="budget-note">
              One whole version. Exact cents; no rounding. Checked before quote
              and confirmation.
            </small>
          </label>
          {budgetReason && (
            <div className="error-message" role="alert">
              {budgetReason}
            </div>
          )}
          {marketplace?.mode === "xrpl-testnet" && !quote && (
            <label className="field">
              Buyer wallet address
              <input
                value={buyerAddress}
                onChange={(event) => setBuyerAddress(event.target.value)}
                placeholder="r…"
                autoComplete="off"
              />
              <small>
                Classic address of your external testnet wallet. Never enter a
                seed or private key.
              </small>
            </label>
          )}
          <Failure error={error} />
          {recoveryId && !quote && (
            <div className="quiet-note">
              <p className="fine-print">
                Quote {recoveryId} is retained. Retry its lookup before starting
                another purchase.
              </p>
              <button
                className="button secondary"
                disabled={Boolean(busy)}
                onClick={() => void recoverQuote(recoveryId)}
              >
                Retry quote recovery
              </button>
            </div>
          )}
          {!quote ? (
            <>
              <p className="buyer-choice">
                {selected ? (
                  <>
                    <strong>{selected.title}</strong>
                    <span>
                      {usd(selected.price_minor)} · version{" "}
                      {selected.dataset_version}
                    </span>
                  </>
                ) : (
                  "Choose a Resource to inspect an exact quote."
                )}
              </p>
              <button
                className="button primary"
                disabled={
                  !selected ||
                  Boolean(busy) ||
                  marketplace?.mode === "disabled" ||
                  !marketplace
                }
                onClick={() => void obtainQuote()}
              >
                Request quote
              </button>
            </>
          ) : (
            <>
              <div className="buyer-quote-status">
                <span
                  className={`badge ${quote.status === "paid" ? "approved" : "submitted"}`}
                >
                  {quote.status === "paid"
                    ? "Paid · delivery authorized"
                    : quote.status === "pending"
                      ? "Pending · no new payment"
                      : quote.status === "failed"
                        ? "Payment refused"
                        : expired
                          ? "Quote expired"
                          : "Quote ready"}
                </span>
                <strong>{usd(quote.price_minor)}</strong>
              </div>
              <h3>{quote.title}</h3>
              <dl className="buyer-evidence">
                <div>
                  <dt>Quote</dt>
                  <dd>{quote.id}</dd>
                </div>
                <div>
                  <dt>Version / bytes</dt>
                  <dd>
                    {quote.dataset_version} /{" "}
                    {quote.size_bytes.toLocaleString()}
                  </dd>
                </div>
                <div>
                  <dt>Mode / network</dt>
                  <dd>
                    {quote.mode} / {quote.network}
                  </dd>
                </div>
                <div>
                  <dt>Expires (UTC)</dt>
                  <dd>{quote.expires_at}</dd>
                </div>
                <div>
                  <dt>SHA-256</dt>
                  <dd>{quote.sha256}</dd>
                </div>
              </dl>
              {quote.status !== "paid" && quote.mode === "xrpl-testnet" && (
                <>
                  <div className="quiet-note">
                    <strong>Pay once using your external testnet wallet</strong>
                    <dl className="buyer-evidence">
                      <div>
                        <dt>From</dt>
                        <dd>{quote.buyer_address}</dd>
                      </div>
                      <div>
                        <dt>Destination</dt>
                        <dd>{quote.pay_to}</dd>
                      </div>
                      <div>
                        <dt>Exact native XRP drops</dt>
                        <dd>{quote.amount_drops}</dd>
                      </div>
                      <div>
                        <dt>MemoData (hex)</dt>
                        <dd>
                          {Array.from(
                            new TextEncoder().encode(quote.memo),
                            (byte) => byte.toString(16).padStart(2, "0"),
                          ).join("")}
                        </dd>
                      </div>
                    </dl>
                    <p className="fine-print">
                      Use a Payment with this UTF-8 quote memo (hex encoded).
                      Test XRP only. The server verifies public ledger evidence
                      and never signs payments.
                    </p>
                  </div>
                  <label className="field">
                    Transaction hash
                    <input
                      value={hash}
                      onChange={(event) => setHash(event.target.value)}
                      readOnly={Boolean(quote.transaction_hash)}
                      maxLength={64}
                      autoComplete="off"
                    />
                    <small>
                      Paste your real testnet transaction hash. Pending or
                      uncertain results require rechecking the same payment.
                    </small>
                  </label>
                </>
              )}
              {(quote.status === "quoted" || quote.status === "pending") && (
                <button
                  className="button primary"
                  disabled={
                    Boolean(busy) ||
                    (expired &&
                      !quote.transaction_hash &&
                      quote.status !== "pending")
                  }
                  onClick={() => void confirm()}
                >
                  {quote.status === "pending"
                    ? "Recheck payment"
                    : quote.mode === "simulated"
                      ? "Confirm simulated purchase"
                      : "Verify testnet payment"}
                </button>
              )}
              {quote.status === "pending" && (
                <p className="validation-warnings" role="status">
                  Payment is not yet verified. Keep this quote and recheck the
                  same hash. Do not send another payment.
                </p>
              )}
              {expired && quote.status === "quoted" && (
                <p className="validation-warnings">
                  Quote expired. Choose the Resource again for a fresh quote.
                </p>
              )}
              {quote.status === "paid" && (
                <div className="buyer-receipt">
                  <h3>Purchase receipt</h3>
                  <dl className="buyer-evidence">
                    <div>
                      <dt>Receipt</dt>
                      <dd>{quote.receipt_id}</dd>
                    </div>
                    <div>
                      <dt>Paid (UTC)</dt>
                      <dd>{quote.paid_at}</dd>
                    </div>
                    <div>
                      <dt>
                        {quote.mode === "simulated"
                          ? "Simulation evidence"
                          : "Transaction"}
                      </dt>
                      <dd>
                        {quote.transaction_hash || "SIMULATED / NO REAL MONEY"}
                      </dd>
                    </div>
                  </dl>
                  <button
                    className="button primary"
                    disabled={Boolean(busy)}
                    onClick={() => void deliver()}
                  >
                    Download and analyze CSV
                  </button>
                  <button
                    className="button secondary"
                    onClick={() => void copyEvidence()}
                  >
                    Copy receipt evidence
                  </button>
                  {copied && <p role="status">Receipt evidence copied.</p>}
                </div>
              )}
            </>
          )}
          {busy && (
            <p className="buyer-busy" role="status">
              {busy}
            </p>
          )}
          {downloadUrl && (
            <div className="success-message">
              <strong>SHA-256 verified · exact bytes match</strong>
              <p>The original CSV passed digest and size checks.</p>
              <a
                className="button secondary"
                href={downloadUrl}
                download={`sliver-${quote?.resource_id}-v${quote?.dataset_version}.csv`}
              >
                Download verified CSV
              </a>
            </div>
          )}
          <p className="fine-print">
            Local demo purchase access belongs to this browser session. Signing
            in, signing out or session expiry loses access. Only the quote ID is
            kept for reload recovery; no purchased CSV is stored in browser
            storage.
          </p>
        </aside>
      </div>
      {analysis && (
        <section
          className="buyer-analysis panel"
          aria-labelledby="analysis-title"
        >
          <p className="eyebrow">05 / Computed locally from verified CSV</p>
          <h2 id="analysis-title">
            {analysis.routes ? "Route comparison" : "CSV summary"}
          </h2>
          <p className="buyer-answer">{analysis.recommendation}</p>
          <div className="data-facts">
            <span>{analysis.rowCount} data rows</span>
            <span>{analysis.columns.length} columns</span>
            {analysis.period && <span>{analysis.period}</span>}
            <span>
              Source:{" "}
              {(
                selected ?? items.find((item) => item.id === quote?.resource_id)
              )?.provenance.source ?? quote?.title}{" "}
              · version {quote?.dataset_version}
            </span>
          </div>
          {analysis.routes ? (
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Route comparison"
            >
              <table>
                <thead>
                  <tr>
                    <th scope="col">Route</th>
                    <th scope="col">Observations</th>
                    <th scope="col">Mean delay (minutes)</th>
                    <th scope="col">On-time deliveries</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.routes.map((route) => (
                    <tr key={route.route}>
                      <th scope="row">{route.route}</th>
                      <td>{route.observations}</td>
                      <td>{route.meanDelay.toFixed(1)}</td>
                      <td>{(route.onTimeRate * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="column-list">
              {analysis.columns.map((column) => (
                <code key={column}>{column}</code>
              ))}
            </div>
          )}
          <p className="fine-print">
            Mean delay = sum of delay_minutes ÷ observations. On-time rate =
            true or 1 in delivered_on_time ÷ observations. All valid rows are
            included; no network model or platform buying agent is involved.
          </p>
        </section>
      )}
    </section>
  );
}
