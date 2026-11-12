import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";

import { acceptSellerAgreement, ApiError, getSellerAgreement, type SellerAgreement } from "../api";
import { ErrorMessage, PRIMARY_BUTTON } from "./Form";
import PageHeader from "./PageHeader";

export default function SellerAgreementGate({ children }: { children: ReactNode }) {
  const [agreement, setAgreement] = useState<SellerAgreement | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    request.current = controller;
    getSellerAgreement(controller.signal)
      .then(setAgreement)
      .catch(() => {
        if (!controller.signal.aborted) setLoadError(true);
      });
    return () => controller.abort();
  }, [attempt]);

  function reload() {
    setAgreement(null);
    setChecked(false);
    setLoadError(false);
    setAttempt((previous) => previous + 1);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const signal = request.current?.signal;
    if (!agreement || !signal || !checked || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      setAgreement(await acceptSellerAgreement(agreement, signal));
    } catch (error) {
      if (signal.aborted) return;
      setMessage(error instanceof ApiError ? error.message : "Could not save your acceptance. Try again.");
      if (error instanceof ApiError && error.status === 409) reload();
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  if (agreement?.accepted_at) return <>{children}</>;
  if (loadError) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <ErrorMessage>Could not load the Seller Agreement.</ErrorMessage>
        <button type="button" className={PRIMARY_BUTTON} onClick={reload}>Try again</button>
      </div>
    );
  }
  if (!agreement) return <p className="text-muted" role="status">Loading Seller Agreement…</p>;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={agreement.title}>{agreement.notice}</PageHeader>
      <form onSubmit={submit} className="space-y-5 rounded-xl border border-line bg-white p-6">
        {agreement.sections.map((section) => (
          <section key={section.title}>
            <h2 className="font-semibold">{section.title}</h2>
            <p className="mt-1 text-sm text-muted">{section.text}</p>
          </section>
        ))}
        <p className="text-xs text-muted">Version {agreement.version}</p>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            required
            checked={checked}
            disabled={busy}
            onChange={(event) => setChecked(event.target.checked)}
          />
          I agree to the Seller Agreement
        </label>
        {message ? <ErrorMessage>{message}</ErrorMessage> : null}
        <button type="submit" disabled={!checked || busy} className={PRIMARY_BUTTON}>
          {busy ? "Saving…" : "Accept and continue"}
        </button>
      </form>
    </div>
  );
}
