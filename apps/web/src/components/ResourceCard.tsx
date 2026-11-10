import { Link } from "react-router";

import { formatCategory, formatPrice, formatRange } from "../format";
import type { PublicResource } from "../types";
import { ExchangeIcon } from "./ExchangeIcons";

export default function ResourceCard({
  resource,
}: {
  resource: PublicResource;
}) {
  const time = resource.coverage.time;
  return (
    <li className="resource-sheet">
      <div className="resource-sheet-top">
        <span className="resource-category">
          {formatCategory(resource.category)}
        </span>
        <span className="resource-format">
          CSV <span>/</span> {resource.coverage.slice ? "SLICE" : "DATASET"}
        </span>
      </div>
      <h3 className="resource-title">
        <Link to={`/resources/${resource.id}`}>{resource.title}</Link>
      </h3>
      <p className="resource-description">{resource.description}</p>
      <dl className="resource-facts">
        <Meta label="Rows" value={resource.row_count.toLocaleString("en-US")} />
        <Meta label="Columns" value={String(resource.columns.length)} />
        {time ? (
          <Meta label="Coverage" value={formatRange(time.start, time.end)} />
        ) : null}
        <Meta label="Seller" value={resource.seller.name} />
      </dl>
      <div className="resource-sheet-bottom">
        <div>
          <strong>{formatPrice(resource.price.amount_minor)}</strong>
          <span>per purchase</span>
        </div>
        <Link
          to={`/resources/${resource.id}`}
          className="resource-open"
          aria-label={`View ${resource.title}`}
        >
          <ExchangeIcon name="arrow" />
        </Link>
      </div>
      {resource.custom_slices.available ? (
        <span className="resource-custom">
          <span />
          Custom slices available
        </span>
      ) : null}
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
