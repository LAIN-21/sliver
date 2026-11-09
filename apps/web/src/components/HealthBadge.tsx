import { useEffect, useState } from "react";

import { getHealth, type HealthStatus } from "../api";

type State = { kind: "loading" } | { kind: "unreachable" } | { kind: "health"; health: HealthStatus };

const POLL_MS = 10_000;

export default function HealthBadge() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      getHealth(controller.signal)
        .then((health) => setState({ kind: "health", health }))
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) setState({ kind: "unreachable" });
        });
    };
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, []);

  if (state.kind === "loading") return <Badge tone="neutral" label="Checking API…" />;
  if (state.kind === "unreachable") return <Badge tone="bad" label="API unreachable" />;
  const { health } = state;
  if (health.status === "ok") return <Badge tone="good" label="API, database and storage ready" />;
  const down = Object.entries(health.checks)
    .filter(([, value]) => value !== "ok")
    .map(([name]) => name)
    .join(", ");
  return <Badge tone="bad" label={`Degraded: ${down} unavailable`} />;
}

function Badge({ tone, label }: { tone: "good" | "bad" | "neutral"; label: string }) {
  const dot = { good: "bg-emerald-500", bad: "bg-rose-500", neutral: "bg-slate-300" }[tone];
  return (
    <span role="status" className="inline-flex items-center gap-2">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
