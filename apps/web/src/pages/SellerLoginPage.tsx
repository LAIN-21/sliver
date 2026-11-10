import { type FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../api";
import { ErrorMessage, Field, INPUT, PRIMARY_BUTTON } from "../components/Form";
import PageHeader from "../components/PageHeader";
import { useSession } from "../session";
import "../components/ProductPages.css";

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
    <div className="seller-login">
      <section
        className="seller-login__editorial"
        aria-labelledby="seller-login-intro"
      >
        <p className="seller-login__eyebrow">Sliver / Seller workspace</p>
        <h2 id="seller-login-intro">
          From dataset
          <br />
          to discovery.
        </h2>
        <p className="seller-login__intro">
          Prepare your data for the questions only it can answer.
        </p>
        <figure className="seller-login__diagram">
          <div className="seller-login__plates" aria-hidden="true">
            <div className="seller-login__plate seller-login__plate--back" />
            <div className="seller-login__plate seller-login__plate--middle" />
            <div className="seller-login__plate seller-login__plate--front">
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>
            <div className="seller-login__sliver">
              <span />
              <span />
              <span />
            </div>
          </div>
          <figcaption>
            One dataset. Individually useful slivers.
            <span>Schematic illustration</span>
          </figcaption>
        </figure>
        <ol className="seller-login__pipeline" aria-label="Seller workflow">
          <li>
            <span>01</span>
            <div>
              <strong>Upload & inspect</strong>
              <p>Review the schema, quality and privacy findings.</p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>Review your slivers</strong>
              <p>Check the Resources prepared from your dataset.</p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>Set a price & publish</strong>
              <p>Choose what reaches the marketplace.</p>
            </div>
          </li>
        </ol>
      </section>
      <section
        className="seller-login__form-panel"
        aria-label="Seller account sign-in"
      >
        <p className="seller-login__form-eyebrow">Your workspace</p>
        <PageHeader title="Seller sign-in">
          Demo sellers and the reviewer sign in with the passwords set in your
          .env (see docs/DEVELOPMENT.md).
        </PageHeader>
        <form onSubmit={submit} className="seller-login__form">
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
          <button
            type="submit"
            disabled={busy}
            className={`${PRIMARY_BUTTON} w-full`}
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="seller-login__account-note">
          Access is for existing demo accounts. There is no public sign-up.
        </p>
      </section>
    </div>
  );
}
