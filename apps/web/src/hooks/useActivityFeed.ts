import { useCallback, useEffect, useState } from "react";

import { mergeEvents } from "../activity";
import { ApiError, getActivity } from "../api";
import type { ActivityEvent, ActivityType } from "../types";
import { type StreamStatus, useActivityStream } from "./useActivityStream";

export type Feed = {
  events: ActivityEvent[]; // newest first
  loading: boolean;
  error: string | null;
  status: StreamStatus;
};

/** The latest activity, kept current by the live stream. */
export function useActivityFeed(limit: number, type?: ActivityType): Feed {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getActivity({ limit, type }, controller.signal)
      .then((feed) => {
        setEvents(feed.items);
        setCursor(feed.cursor);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof ApiError ? reason.message : "Activity could not be loaded.");
      });
    return () => controller.abort();
  }, [limit, type]);

  const onEvent = useCallback(
    (event: ActivityEvent) => {
      if (type && event.type !== type) return;
      setEvents((current) => mergeEvents(current, [event], Math.max(limit, 300)));
    },
    [limit, type],
  );
  const status = useActivityStream(cursor, onEvent);

  return { events, loading: cursor === null && error === null, error, status };
}
