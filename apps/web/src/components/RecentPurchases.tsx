import { Link } from "react-router";

import { formatAgo, formatAmount, formatPrice } from "../format";
import { useActivityFeed } from "../hooks/useActivityFeed";
import { useNow } from "../hooks/useActivityStream";
import { LiveBadge, TxLink } from "./ActivityBits";

/** A compact, live strip of the latest completed agent purchases. */
export default function RecentPurchases() {
  const feed = useActivityFeed(4, "delivered");
  const now = useNow();
  // A replay re-delivers an earlier purchase; show each purchase once.
  const seen = new Set<string>();
  const purchases = feed.events.filter((event) => !seen.has(event.payment_id) && seen.add(event.payment_id)).slice(0, 4);
  if (purchases.length === 0) return null;

  return (
    <section aria-labelledby="recent-heading" className="mb-6">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="recent-heading" className="flex items-center gap-3 text-sm font-semibold">
          Recent agent purchases
          <LiveBadge status={feed.status} />
        </h2>
        <Link to="/activity" className="text-sm font-medium text-brand hover:underline">
          All activity →
        </Link>
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {purchases.map((event, index) => (
          <li
            key={event.payment_id}
            className={`animate-step-in min-w-0 rounded-lg border border-line bg-white px-3 py-2.5 ${index > 1 ? "hidden sm:block" : ""}`}
          >
            <Link to={`/purchases/${event.payment_id}`} className="block truncate text-sm font-medium hover:text-brand">
              {event.resource.title}
            </Link>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
              <span className="font-medium text-emerald-700">✓ Delivered</span>
              <span className="tabular-nums">
                {formatPrice(event.amount.usd_minor)} · {formatAmount(event.amount.value, event.amount.asset)}
              </span>
              <time dateTime={event.at}>{formatAgo(event.at, now)}</time>
            </p>
            {event.transaction ? (
              <p className="mt-0.5 text-xs">
                <TxLink hash={event.transaction.hash} size={5} />
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
