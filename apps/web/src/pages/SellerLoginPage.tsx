import { type FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../api";
import { ErrorMessage, Field, INPUT, PRIMARY_BUTTON } from "../components/Form";
import PageHeader from "../components/PageHeader";
import { useSession } from "../session";

export default function SellerLoginPage() {
  const { account, login } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Only same-app paths, so a crafted link cannot bounce the user elsewhere after sign-in.
  const requested = params.get("next") ?? "";
  const next = requested.startsWith("/sell") ? requested : "/sell";

  if (account) return <Navigate to={next} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(next, { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <PageHeader title="Seller sign-in">Demo sellers and the reviewer sign in with the passwords set in your .env (see docs/DEVELOPMENT.md).</PageHeader>
      <form onSubmit={submit} className="space-y-4 rounded-xl border border-line bg-white p-6">
        <Field label="Email">
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={INPUT}
            placeholder="harbour-analytics@sliver.local"
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={INPUT}
          />
        </Field>
        {error ? <ErrorMessage>{error}</ErrorMessage> : null}
        <button type="submit" disabled={busy} className={`${PRIMARY_BUTTON} w-full`}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
