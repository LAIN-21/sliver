import { Link } from "react-router";

import { formatCategory, formatPrice, formatRange } from "../format";
import type { PublicResource } from "../types";

export default function ResourceCard({ resource }: { resource: PublicResource }) {
  const time = resource.coverage.time;
  return (
    <li className="rounded-xl border border-line bg-white p-5 transition hover:border-brand/40 hover:shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <span className="rounded-full bg-surface px-2.5 py-1 text-xs font-medium text-muted">
            {formatCategory(resource.category)}
          </span>
          <h2 className="mt-2 text-lg font-semibold [overflow-wrap:anywhere]">
            <Link to={`/resources/${resource.id}`} className="hover:text-brand">
              {resource.title}
            </Link>
          </h2>
        </div>
        <p className="text-lg font-semibold tabular-nums">{formatPrice(resource.price.amount_minor)}</p>
      </div>
      <p className="mt-2 line-clamp-2 text-sm text-muted">{resource.description}</p>
      <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <Meta label="Rows" value={resource.row_count.toLocaleString("en-US")} />
        <Meta label="Columns" value={String(resource.columns.length)} />
        {time ? <Meta label="Coverage" value={formatRange(time.start, time.end)} /> : null}
        <Meta label="Seller" value={resource.seller.name} />
      </dl>
    </li>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
