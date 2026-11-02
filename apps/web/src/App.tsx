import {
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { FormEvent, ReactElement } from "react";
import { ApiError, getSession, login, logout, request } from "./api";
import type {
  Dataset,
  Preview,
  PublicProvenance,
  PublicResource,
  Resource,
  Session,
  User,
} from "./types";

const money = (amount: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    amount / 100,
  );
const date = (value: string) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(parsed);
};
const statuses = {
  draft: "Draft",
  submitted: "Awaiting review",
  approved: "Published",
  rejected: "Rejected",
};

function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof Error
      ? error.message
      : "Something went wrong. Please try again.";
  return (
    <div className="error-message" role="alert">
      <strong>{message}</strong>
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

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactElement<{ id?: string; "aria-describedby"?: string }>;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, {
        id,
        "aria-describedby": hint ? hintId : undefined,
      })}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="loading" role="status">
      <span>{label}</span>
      <div />
      <div />
      <div />
    </div>
  );
}

function SourceDetails({ provenance }: { provenance: PublicProvenance }) {
  return (
    <dl className="source-details">
      <div>
        <dt>Source</dt>
        <dd>{provenance.source}</dd>
      </div>
      <div>
        <dt>Collection method</dt>
        <dd>{provenance.method}</dd>
      </div>
      <div>
        <dt>Collected</dt>
        <dd>{date(provenance.collected_at)}</dd>
      </div>
      <div>
        <dt>Coverage</dt>
        <dd>{provenance.coverage}</dd>
      </div>
    </dl>
  );
}

function StatusRail({ status }: { status: Resource["status"] }) {
  const position = { draft: 0, submitted: 1, approved: 2, rejected: 1 }[status];
  return (
    <ol className="status-rail" aria-label="Publication progress">
      {[
        "Prepared",
        status === "rejected" ? "Rejected" : "Review",
        "Published",
      ].map((step, index) => (
        <li
          className={index <= position ? "reached" : ""}
          key={index}
          aria-current={index === position ? "step" : undefined}
        >
          <span>{String(index + 1).padStart(2, "0")}</span>
          {step}
        </li>
      ))}
    </ol>
  );
}

function LoginForm({
  onLogin,
  onCancel,
}: {
  onLogin: (session: Session) => Promise<void>;
  onCancel: () => void;
}) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await onLogin(
        await login(String(form.get("email")), String(form.get("password"))),
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="login-layout" aria-labelledby="login-title">
      <div>
        <p className="eyebrow">Your workspace</p>
        <h1 id="login-title">Sign in to Sliver</h1>
        <p className="intro">
          Prepare data for publication, or review a seller’s submission.
        </p>
        <div className="quiet-note">
          <strong>Local demo accounts</strong>
          <p>
            Use your configured seller or reviewer account. Passwords are set
            during local setup.
          </p>
        </div>
      </div>
      <form className="panel login-form" onSubmit={submit}>
        <Field label="Email">
          <input
            autoComplete="username"
            type="email"
            name="email"
            required
            autoFocus
          />
        </Field>
        <Field label="Password">
          <input
            autoComplete="current-password"
            type="password"
            name="password"
            required
          />
        </Field>
        <ErrorMessage error={error} />
        <button className="button primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <button className="button text" onClick={onCancel} type="button">
          Back to catalog
        </button>
      </form>
    </section>
  );
}

function Catalog({
  resources,
  onPublish,
}: {
  resources: PublicResource[];
  onPublish: () => void;
}) {
  return (
    <section aria-labelledby="catalog-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Public catalog</p>
          <h1 id="catalog-title">Data, with a source.</h1>
          <p className="intro">
            Discover reviewed Resources with declared provenance and a price for
            one exact version.
          </p>
        </div>
        <div className="section-count">
          <strong>{String(resources.length).padStart(2, "0")}</strong>
          <span>published Resources</span>
        </div>
      </div>
      <div className="catalog-note">
        <span className="tiny-square" />
        Metadata is public. Dataset contents remain private.
        <span className="note-end">
          Purchasing is not enabled in this demo.
        </span>
      </div>
      {resources.length === 0 ? (
        <div className="empty-state">
          <span className="empty-index">01 / 03</span>
          <h2>The first Resource starts with an upload.</h2>
          <p>
            A seller prepares a CSV and declares its source. A separate reviewer
            approves it before it appears here.
          </p>
          <button className="button primary" onClick={onPublish}>
            Sign in to publish
          </button>
        </div>
      ) : (
        <div className="catalog-list">
          {resources.map((resource, index) => (
            <article
              className="catalog-resource"
              key={resource.id}
              aria-label={`Published Resource ${resource.title}`}
            >
              <div className="resource-index">
                {String(index + 1).padStart(2, "0")}
                <span>RESOURCE</span>
              </div>
              <div className="resource-main">
                <div className="resource-topline">
                  <span className="badge approved">
                    Reviewed for publication
                  </span>
                  <span className="mono">
                    Version {resource.dataset_version}
                  </span>
                </div>
                <h2>{resource.title}</h2>
                <p className="resource-description">{resource.description}</p>
                <div className="data-facts">
                  <span>
                    <strong>{resource.row_count.toLocaleString()}</strong> rows
                  </span>
                  <span>
                    <strong>{resource.columns.length}</strong> columns
                  </span>
                  <span>Whole CSV version</span>
                </div>
                <details>
                  <summary>Schema and provenance</summary>
                  <div className="column-list">
                    {resource.columns.map((column) => (
                      <code key={column}>{column}</code>
                    ))}
                  </div>
                  <SourceDetails provenance={resource.provenance} />
                </details>
                <p className="fine-print">
                  Publication review does not certify factual accuracy or
                  ownership.
                </p>
              </div>
              <div className="resource-price">
                <strong>{money(resource.price_minor)}</strong>
                <span>USD · one version</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function UploadForm({
  onUploaded,
}: {
  onUploaded: (dataset: Dataset) => Promise<void>;
}) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const values = new FormData(element);
    const file = values.get("file");
    setError(null);
    if (!(file instanceof File) || !file.size) {
      setError(new Error("Choose a nonempty CSV file."));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError(new Error("The CSV must be 5 MiB or smaller."));
      return;
    }
    const body = new FormData();
    body.append("file", file);
    body.append("title", String(values.get("title")));
    body.append(
      "provenance",
      JSON.stringify({
        source: values.get("source"),
        method: values.get("method"),
        collected_at: `${values.get("collected_at")}T00:00:00Z`,
        coverage: values.get("coverage"),
        rights_statement: values.get("rights_statement"),
      }),
    );
    setBusy(true);
    try {
      const dataset = await request<Dataset>("/datasets", {
        method: "POST",
        body,
      });
      element.reset();
      await onUploaded(dataset);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="panel upload-form"
      onSubmit={submit}
      aria-labelledby="upload-title"
    >
      <div className="panel-heading">
        <span className="step-number">01</span>
        <div>
          <h2 id="upload-title">Upload a dataset</h2>
          <p>The file and rights declaration stay private.</p>
        </div>
      </div>
      <Field label="Dataset title">
        <input
          name="title"
          required
          maxLength={160}
          placeholder="Singapore port observations"
        />
      </Field>
      <Field
        label="CSV file"
        hint="UTF-8 CSV · up to 5 MiB, 10,000 rows and 100 columns"
      >
        <input type="file" name="file" accept=".csv,text/csv" required />
      </Field>
      <div className="field-pair">
        <Field label="Source">
          <input
            name="source"
            required
            maxLength={500}
            placeholder="Who collected this data?"
          />
        </Field>
        <Field label="Collection date">
          <input type="date" name="collected_at" required />
        </Field>
      </div>
      <Field label="Collection method">
        <input
          name="method"
          required
          maxLength={500}
          placeholder="How were the observations collected?"
        />
      </Field>
      <Field label="Coverage">
        <input
          name="coverage"
          required
          maxLength={500}
          placeholder="Location, period and scope"
        />
      </Field>
      <Field
        label="Rights declaration"
        hint="Private to you and reviewers. Explain your right to publish and any use restrictions."
      >
        <textarea name="rights_statement" required maxLength={2000} rows={3} />
      </Field>
      <ErrorMessage error={error} />
      <button className="button primary" type="submit" disabled={busy}>
        {busy ? "Uploading and validating…" : "Upload and validate"}
      </button>
    </form>
  );
}

function PrivatePreview({ dataset }: { dataset: Dataset }) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const controller = new AbortController();
    request<Preview>(`/datasets/${dataset.id}/preview`, {
      signal: controller.signal,
    })
      .then(setPreview)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure);
      });
    return () => controller.abort();
  }, [dataset.id]);
  return (
    <div className="private-preview">
      <div className="private-label">
        Private preview · seller and reviewer only
      </div>
      <ErrorMessage error={error} />
      {!preview && !error ? (
        <Loading label="Loading private preview…" />
      ) : (
        preview && (
          <>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label={`Private preview of ${dataset.title}`}
            >
              <table>
                <thead>
                  <tr>
                    {preview.columns.map((column) => (
                      <th key={column} scope="col">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, index) => (
                    <tr key={index}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>
                          {cell || <span className="muted">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.truncated && (
              <p className="fine-print">
                Showing a limited preview of{" "}
                {dataset.row_count.toLocaleString()} rows.
              </p>
            )}
          </>
        )
      )}
    </div>
  );
}

function DatasetDetails({
  dataset,
  reviewer = false,
}: {
  dataset: Dataset;
  reviewer?: boolean;
}) {
  const [showPreview, setShowPreview] = useState(false);
  return (
    <div className="dataset-details">
      <div className="resource-topline">
        <span className="badge">File checks passed</span>
        <span className="mono">Version {dataset.version}</span>
      </div>
      <h3>{dataset.title}</h3>
      <p className="fine-print">
        {dataset.filename} · {dataset.row_count.toLocaleString()} rows ·{" "}
        {dataset.columns.length} columns
      </p>
      <div className="column-list">
        {dataset.columns.map((column) => (
          <code key={column}>{column}</code>
        ))}
      </div>
      {dataset.validation.warnings.length > 0 && (
        <div className="validation-warnings">
          <strong>Review these findings</strong>
          <ul>
            {dataset.validation.warnings.map((warning, index) => (
              <li key={index}>{warning.message}</li>
            ))}
          </ul>
        </div>
      )}
      <SourceDetails provenance={dataset.provenance} />
      <details>
        <summary>Private rights declaration</summary>
        <p className="declaration">{dataset.provenance.rights_statement}</p>
      </details>
      <details>
        <summary>File fingerprint</summary>
        <code className="fingerprint">{dataset.sha256}</code>
        <p className="fine-print">
          This fingerprint identifies the original uploaded bytes.
        </p>
      </details>
      <button
        className="button secondary"
        onClick={() => setShowPreview(!showPreview)}
        aria-expanded={showPreview}
      >
        {showPreview ? "Hide private preview" : "View private preview"}
      </button>
      {showPreview && <PrivatePreview dataset={dataset} />}
      {reviewer && (
        <p className="fine-print">
          File validation checks structure. Review the declaration independently
          before approving publication.
        </p>
      )}
    </div>
  );
}

function ResourceForm({
  dataset,
  onCreated,
}: {
  dataset: Dataset;
  onCreated: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const price = String(form.get("price")).trim();
    if (!/^\d+(\.\d{1,2})?$/.test(price)) {
      setError(
        new Error("Enter a USD price with no more than two decimal places."),
      );
      return;
    }
    const [dollars, cents = ""] = price.split(".");
    const priceMinor = Number(dollars) * 100 + Number(cents.padEnd(2, "0"));
    if (
      !Number.isSafeInteger(priceMinor) ||
      priceMinor <= 0 ||
      priceMinor > 100_000_000
    ) {
      setError(new Error("The price must be between $0.01 and $1,000,000.00."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await request<Resource>("/resources", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: dataset.id,
          title: form.get("title"),
          description: form.get("description"),
          price_minor: priceMinor,
          currency: "USD",
        }),
      });
      await onCreated();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="resource-form"
      onSubmit={submit}
      aria-label="Create Resource"
    >
      <div className="panel-heading">
        <span className="step-number">02</span>
        <div>
          <h3>Create a Resource</h3>
          <p>Offer this entire CSV version at a fixed price.</p>
        </div>
      </div>
      <Field label="Resource title">
        <input
          name="title"
          required
          defaultValue={dataset.title}
          maxLength={160}
        />
      </Field>
      <Field
        label="Public description"
        hint="Describe the data without copying private records into this field."
      >
        <textarea name="description" required maxLength={2000} rows={3} />
      </Field>
      <Field
        label="Price (USD)"
        hint="One whole CSV version. Payments are not enabled in this demo."
      >
        <input name="price" inputMode="decimal" required placeholder="12.50" />
      </Field>
      <ErrorMessage error={error} />
      <button className="button primary" disabled={busy}>
        {busy ? "Creating draft…" : "Create draft Resource"}
      </button>
    </form>
  );
}

function SellerResources({
  resources,
  onChange,
}: {
  resources: Resource[];
  onChange: () => Promise<void>;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  async function submit(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await request<Resource>(`/resources/${id}/submit`, { method: "POST" });
      await onChange();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusyId(null);
    }
  }
  return (
    <section
      className="resources-section"
      aria-labelledby="seller-resources-title"
    >
      <div className="section-heading">
        <h2 id="seller-resources-title">Your Resources</h2>
        <span className="count-label">{resources.length} total</span>
      </div>
      <ErrorMessage error={error} />
      {resources.length === 0 ? (
        <p className="inline-empty">
          Select an uploaded dataset to prepare your first Resource.
        </p>
      ) : (
        resources.map((resource) => (
          <article
            className="owned-resource"
            key={resource.id}
            aria-label={`Resource ${resource.title}`}
          >
            <div className="owned-heading">
              <div>
                <span className={`badge ${resource.status}`}>
                  {statuses[resource.status]}
                </span>
                <h3>{resource.title}</h3>
              </div>
              <strong className="price-small">
                {money(resource.price_minor)}
              </strong>
            </div>
            <p>{resource.description}</p>
            <StatusRail status={resource.status} />
            {resource.review_reason && (
              <p className="review-reason">
                <strong>Reviewer note:</strong> {resource.review_reason}
              </p>
            )}
            {resource.status === "draft" && (
              <button
                className="button secondary"
                disabled={busyId !== null}
                onClick={() => void submit(resource.id)}
              >
                {busyId === resource.id ? "Submitting…" : "Submit for review"}
              </button>
            )}
            {resource.status === "rejected" && (
              <p className="fine-print">
                To address the review, upload a corrected dataset and create a
                new Resource.
              </p>
            )}
          </article>
        ))
      )}
    </section>
  );
}

function SellerWorkspace({
  datasets,
  resources,
  onChange,
  notify,
}: {
  datasets: Dataset[];
  resources: Resource[];
  onChange: () => Promise<void>;
  notify: (message: string) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = datasets.find((dataset) => dataset.id === selectedId);
  return (
    <section aria-labelledby="workspace-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Seller workspace</p>
          <h1 id="workspace-title">Prepare. Review. Publish.</h1>
          <p className="intro">
            Start with a private dataset. Publication needs a separate
            reviewer’s approval.
          </p>
        </div>
        <div className="section-count">
          <strong>{String(datasets.length).padStart(2, "0")}</strong>
          <span>private datasets</span>
        </div>
      </div>
      <div className="workspace-grid">
        <UploadForm
          onUploaded={async (dataset) => {
            await onChange();
            setSelectedId(dataset.id);
            notify(
              "Dataset uploaded. File checks passed; review any findings before creating a Resource.",
            );
          }}
        />
        <section
          className="panel dataset-panel"
          aria-labelledby="datasets-title"
        >
          <div className="panel-heading">
            <span className="step-number">02</span>
            <div>
              <h2 id="datasets-title">Inspect your datasets</h2>
              <p>Original bytes are kept as an immutable version.</p>
            </div>
          </div>
          {datasets.length === 0 ? (
            <div className="inline-empty">
              <p>
                Your private datasets will appear here after a successful
                upload.
              </p>
              <p>Invalid files stay out of the catalog.</p>
            </div>
          ) : (
            <>
              <Field label="Select dataset">
                <select
                  value={selectedId ?? ""}
                  onChange={(event) =>
                    setSelectedId(event.target.value || null)
                  }
                >
                  <option value="">Choose a dataset</option>
                  {datasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.title}
                    </option>
                  ))}
                </select>
              </Field>
              {selected ? (
                <>
                  <DatasetDetails key={selected.id} dataset={selected} />
                  <ResourceForm
                    key={`resource-${selected.id}`}
                    dataset={selected}
                    onCreated={async () => {
                      await onChange();
                      notify(
                        "Draft Resource created. Submit it when it is ready for review.",
                      );
                    }}
                  />
                </>
              ) : (
                <p className="inline-empty">
                  Choose a dataset to inspect its source and prepare a Resource.
                </p>
              )}
            </>
          )}
        </section>
      </div>
      <SellerResources
        resources={resources}
        onChange={async () => {
          await onChange();
          notify("Resource submitted for separate review.");
        }}
      />
    </section>
  );
}

function ReviewCard({
  resource,
  dataset,
  onChange,
}: {
  resource: Resource;
  dataset: Dataset | undefined;
  onChange: () => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await request<Resource>(`/resources/${resource.id}/review`, {
        method: "POST",
        body: JSON.stringify({
          decision: form.get("decision"),
          reason: form.get("reason"),
        }),
      });
      await onChange();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article
      className="panel review-card"
      aria-label={`Review ${resource.title}`}
    >
      <div className="owned-heading">
        <div>
          <span className={`badge ${resource.status}`}>
            {statuses[resource.status]}
          </span>
          <h2>{resource.title}</h2>
        </div>
        <strong className="price-small">{money(resource.price_minor)}</strong>
      </div>
      <p>{resource.description}</p>
      <StatusRail status={resource.status} />
      <button
        className="button secondary"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        {expanded ? "Close inspection" : "Inspect submission"}
      </button>
      {expanded && (
        <div className="review-inspection">
          {dataset ? (
            <DatasetDetails dataset={dataset} reviewer />
          ) : (
            <p className="error-message" role="alert">
              The source dataset is unavailable. Do not approve this submission.
            </p>
          )}
          {resource.status === "submitted" && dataset && (
            <form className="review-form" onSubmit={review}>
              <h3>Record your decision</h3>
              <p className="fine-print">
                Approval immediately publishes the Resource metadata. The
                original CSV stays private.
              </p>
              <Field label="Decision">
                <select name="decision" required defaultValue="">
                  <option value="" disabled>
                    Choose a decision
                  </option>
                  <option value="approve">Approve and publish</option>
                  <option value="reject">Reject submission</option>
                </select>
              </Field>
              <Field label="Review reason">
                <textarea name="reason" required maxLength={2000} rows={3} />
              </Field>
              <ErrorMessage error={error} />
              <button className="button primary" disabled={busy}>
                {busy ? "Recording decision…" : "Record review"}
              </button>
            </form>
          )}
          {resource.review_reason && (
            <p className="review-reason">
              <strong>Reviewer note:</strong> {resource.review_reason}
            </p>
          )}
        </div>
      )}
    </article>
  );
}

function ReviewerWorkspace({
  datasets,
  resources,
  onChange,
}: {
  datasets: Dataset[];
  resources: Resource[];
  onChange: () => Promise<void>;
}) {
  const queue = resources.filter((resource) => resource.status === "submitted");
  const reviewed = resources.filter(
    (resource) =>
      resource.status === "approved" || resource.status === "rejected",
  );
  return (
    <section aria-labelledby="review-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Independent publication review</p>
          <h1 id="review-title">Review the source.</h1>
          <p className="intro">
            Inspect the file findings and private rights declaration before
            deciding what can be published.
          </p>
        </div>
        <div className="section-count">
          <strong>{String(queue.length).padStart(2, "0")}</strong>
          <span>awaiting review</span>
        </div>
      </div>
      {queue.length === 0 ? (
        <div className="empty-state compact">
          <span className="empty-index">02 / 03</span>
          <h2>The review queue is clear.</h2>
          <p>
            Resources appear here after a seller submits them. Drafts remain
            private to their preparation workflow.
          </p>
        </div>
      ) : (
        <div className="review-list">
          {queue.map((resource) => (
            <ReviewCard
              key={resource.id}
              resource={resource}
              dataset={datasets.find(
                (dataset) => dataset.id === resource.dataset_id,
              )}
              onChange={onChange}
            />
          ))}
        </div>
      )}
      {reviewed.length > 0 && (
        <section className="resources-section">
          <div className="section-heading">
            <h2>Previous decisions</h2>
            <span className="count-label">{reviewed.length} reviewed</span>
          </div>
          <div className="review-list">
            {reviewed.map((resource) => (
              <ReviewCard
                key={resource.id}
                resource={resource}
                dataset={datasets.find(
                  (dataset) => dataset.id === resource.dataset_id,
                )}
                onChange={onChange}
              />
            ))}
          </div>
        </section>
      )}
    </section>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<"catalog" | "workspace" | "login">("catalog");
  const [catalog, setCatalog] = useState<PublicResource[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const generation = useRef(0);
  const refresh = useCallback(
    async (nextUser: User | null, signal?: AbortSignal) => {
      const current = ++generation.current;
      setError(null);
      try {
        const [publicData, privateDatasets, privateResources] =
          await Promise.all([
            request<{ items: PublicResource[] }>("/catalog", { signal }),
            nextUser
              ? request<{ items: Dataset[] }>("/datasets", { signal })
              : Promise.resolve({ items: [] as Dataset[] }),
            nextUser
              ? request<{ items: Resource[] }>("/resources", { signal })
              : Promise.resolve({ items: [] as Resource[] }),
          ]);
        if (generation.current !== current || signal?.aborted) return;
        setCatalog(publicData.items);
        setDatasets(privateDatasets.items);
        setResources(privateResources.items);
      } catch (failure) {
        if (generation.current === current && !signal?.aborted) {
          setError(failure);
          throw failure;
        }
      } finally {
        if (generation.current === current && !signal?.aborted)
          setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    void getSession(controller.signal)
      .then(async (session) => {
        if (controller.signal.aborted) return;
        setUser(session.user);
        setReady(true);
        await refresh(session.user, controller.signal);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setError(failure);
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
      generation.current += 1;
    };
  }, [refresh]);

  async function signedIn(session: Session) {
    generation.current += 1;
    setLoading(true);
    setDatasets([]);
    setResources([]);
    setUser(session.user);
    setNotice("");
    setTab("workspace");
    await refresh(session.user);
  }
  async function signOut() {
    setAuthBusy(true);
    setError(null);
    try {
      await logout();
      // Revocation is complete even if creating a new anonymous session fails.
      generation.current += 1;
      setUser(null);
      setDatasets([]);
      setResources([]);
      setNotice("");
      setTab("catalog");
      setReady(false);
      setLoading(false);
      await getSession();
      setReady(true);
      await refresh(null);
    } catch (failure) {
      setError(failure);
    } finally {
      setAuthBusy(false);
    }
  }
  function navigate(nextTab: typeof tab) {
    setNotice("");
    setTab(nextTab);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="header-inner">
          <button
            className="wordmark"
            onClick={() => navigate("catalog")}
            aria-label="Sliver home"
          >
            <span className="brand-mark" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            sliver<span className="wordmark-dot">.</span>
          </button>
          <nav aria-label="Main navigation">
            <button
              className={tab === "catalog" ? "active" : ""}
              aria-current={tab === "catalog" ? "page" : undefined}
              onClick={() => navigate("catalog")}
            >
              Catalog
            </button>
            {user && (
              <button
                className={tab === "workspace" ? "active" : ""}
                aria-current={tab === "workspace" ? "page" : undefined}
                onClick={() => navigate("workspace")}
              >
                {user.role === "reviewer" ? "Review queue" : "Seller workspace"}
              </button>
            )}
          </nav>
          <div className="header-account">
            <span className="demo-indicator">Local demo</span>
            {user ? (
              <>
                <span className="account-email" title={user.email}>
                  {user.email}
                </span>
                <button
                  className="button secondary small"
                  onClick={() => void signOut()}
                  disabled={authBusy}
                >
                  {authBusy ? "Signing out…" : "Sign out"}
                </button>
              </>
            ) : (
              <button
                className="button secondary small"
                disabled={!ready}
                onClick={() => navigate("login")}
              >
                Sign in
              </button>
            )}
          </div>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <div className="main-inner">
          {notice && (
            <div className="success-message" role="status">
              {notice}
            </div>
          )}
          <ErrorMessage error={error} />
          {Boolean(error) && (
            <button
              className="button secondary retry-button"
              onClick={() => {
                void getSession()
                  .then(async (session) => {
                    setUser(session.user);
                    setReady(true);
                    await refresh(session.user);
                  })
                  .catch(setError);
              }}
            >
              Retry connection
            </button>
          )}
          {!ready && loading ? (
            <Loading label="Connecting to your workspace…" />
          ) : tab === "login" && !user ? (
            <LoginForm
              onLogin={signedIn}
              onCancel={() => navigate("catalog")}
            />
          ) : loading ? (
            <Loading label="Loading Resources…" />
          ) : tab === "workspace" && user ? (
            user.role === "seller" ? (
              <SellerWorkspace
                key={user.id}
                datasets={datasets}
                resources={resources}
                onChange={() => refresh(user)}
                notify={setNotice}
              />
            ) : (
              <ReviewerWorkspace
                datasets={datasets}
                resources={resources}
                onChange={async () => {
                  await refresh(user);
                  setNotice(
                    "Review recorded. The catalog includes approved Resources only.",
                  );
                }}
              />
            )
          ) : (
            <Catalog
              resources={catalog}
              onPublish={() => navigate(user ? "workspace" : "login")}
            />
          )}
        </div>
      </main>
      <footer className="site-footer">
        <span>Sliver / Source before sale.</span>
        <span>Local demonstration · CSV publication only · No payments</span>
      </footer>
    </div>
  );
}
