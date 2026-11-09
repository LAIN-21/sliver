import { useEffect, useRef, useState } from "react";

import { activityStreamUrl } from "../api";
import type { ActivityEvent } from "../types";

export type StreamStatus = "connecting" | "live" | "reconnecting";

const RETRY_MS = 3_000;

/**
 * Follows `/api/activity/stream` from `after` (null waits, e.g. until the first page loads).
 * The browser reconnects with Last-Event-ID on its own; if it gives up, we reopen from the
 * last event we saw, so no step is ever missed or repeated.
 */
export function useActivityStream(
  after: number | null,
  onEvent: (event: ActivityEvent) => void,
  paymentId?: string,
): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  });

  useEffect(() => {
    if (after === null) return;
    let last = after;
    let source: EventSource | null = null;
    let retry: number | undefined;
    let closed = false;

    const open = () => {
      source = new EventSource(activityStreamUrl(last, paymentId));
      source.onopen = () => setStatus("live");
      source.addEventListener("heartbeat", () => setStatus("live"));
      source.addEventListener("activity", (message) => {
        const event = JSON.parse((message as MessageEvent<string>).data) as ActivityEvent;
        if (event.id <= last) return;
        last = event.id;
        setStatus("live");
        handler.current(event);
      });
      source.onerror = () => {
        setStatus("reconnecting");
        if (source?.readyState === EventSource.CLOSED && !closed) {
          retry = window.setTimeout(open, RETRY_MS);
        }
      };
    };
    open();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      source?.close();
    };
  }, [after, paymentId]);

  return status;
}

/** Re-renders every `ms` so relative times ("12 s ago") stay current. */
export function useNow(ms = 10_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(timer);
  }, [ms]);
  return now;
}
