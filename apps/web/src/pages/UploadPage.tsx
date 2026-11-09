import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { ApiError, uploadDataset } from "../api";
import { ErrorMessage, Field, INPUT, PRIMARY_BUTTON } from "../components/Form";
import PageHeader from "../components/PageHeader";
import RequireAccount from "../components/RequireAccount";

const MAX_BYTES = 5 * 1024 * 1024;

export default function UploadPage() {
  return (
    <RequireAccount>{(account) => (account.role === "seller" ? <UploadForm /> : <Navigate to="/sell" replace />)}</RequireAccount>
  );
}

function UploadForm() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const today = new Date().toISOString().slice(0, 10);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) return setError("Choose a non-empty CSV file.");
    if (file.size > MAX_BYTES) return setError("CSV files may be at most 5 MiB.");
    setBusy(true);
    setError(null);
    try {
      const dataset = await uploadDataset(form);
      navigate(`/sell/datasets/${dataset.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Upload failed.");
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <Link to="/sell" className="text-sm font-medium text-brand hover:underline">
        ← Your datasets
      </Link>
      <div className="mt-4">
        <PageHeader title="Upload a dataset">
          Sliver stores the file privately and immutably with its SHA-256, then inspects it. Nothing is published
          from this step.
        </PageHeader>
      </div>
      <form onSubmit={submit} className="space-y-5 rounded-xl border border-line bg-white p-6">
        <Field label="CSV file" hint="UTF-8, header row first, at most 5 MiB, 10,000 rows and 100 columns.">
          <input name="file" type="file" accept=".csv,text/csv" required className={INPUT} />
        </Field>
        <Field label="Title">
          <input name="title" required minLength={3} maxLength={160} className={INPUT} />
        </Field>
        <fieldset className="space-y-4 rounded-lg border border-line p-4">
          <legend className="px-1 text-sm font-semibold">Provenance</legend>
          <Field label="Source" hint="Where the data comes from, e.g. our terminal operating system.">
            <input name="source" required minLength={3} maxLength={300} className={INPUT} />
          </Field>
          <Field label="Collection method" hint="How it was collected or derived.">
            <textarea name="method" required minLength={3} maxLength={1000} rows={3} className={INPUT} />
          </Field>
          <Field label="Collected on (or last updated)">
            <input name="collected_at" type="date" required min="1900-01-01" max={today} className={INPUT} />
          </Field>
        </fieldset>
        <Field label="Rights statement (optional)" hint="Licence or terms buyers should know about.">
          <textarea name="rights_statement" maxLength={1000} rows={2} className={INPUT} />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input name="rights_confirmed" type="checkbox" value="true" required className="mt-1" />
          <span>
            I confirm I have the right to sell this data, and that it contains no personal data I am not allowed to
            share.
          </span>
        </label>
        {error ? <ErrorMessage>{error}</ErrorMessage> : null}
        <button type="submit" disabled={busy} className={PRIMARY_BUTTON}>
          {busy ? "Uploading…" : "Upload and inspect"}
        </button>
      </form>
    </div>
  );
}
