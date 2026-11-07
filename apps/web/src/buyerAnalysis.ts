const MAX_BYTES = 5 * 1024 * 1024;
const MAX_ROWS = 10_000;
const MAX_COLUMNS = 100;

/** Parse decimal USD without floating-point multiplication or rounding. */
export function parseUsd(value: string): number | null {
  const match = /^(0|[1-9]\d{0,12})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match) return null;
  const cents =
    BigInt(match[1]) * 100n + BigInt((match[2] ?? "").padEnd(2, "0"));
  return cents <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(cents) : null;
}

export function usd(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(cents / 100);
}

/** RFC-style quoted CSV, bounded to the upload contract; no heuristic splitting. */
export function parseCsv(bytes: ArrayBuffer): {
  columns: string[];
  rows: string[][];
} {
  if (bytes.byteLength > MAX_BYTES)
    throw new Error("CSV exceeds the 5 MiB local analysis limit.");
  const text = new TextDecoder("utf-8", { fatal: true })
    .decode(bytes)
    .replace(/^\uFEFF/, "");
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let quoted = false;
  let closed = false;
  let started = false;
  const endField = () => {
    record.push(field);
    if (record.length > MAX_COLUMNS)
      throw new Error("CSV exceeds 100 columns.");
    field = "";
    closed = false;
    started = false;
  };
  const endRecord = () => {
    endField();
    records.push(record);
    record = [];
    if (records.length > MAX_ROWS + 1)
      throw new Error("CSV exceeds 10,000 data rows.");
  };
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
          closed = true;
        }
      } else field += char;
    } else if (char === ",") endField();
    else if (char === "\r" || char === "\n") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      endRecord();
    } else if (char === '"' && !started && !closed) {
      quoted = true;
      started = true;
    } else {
      if (closed || char === '"')
        throw new Error("CSV contains an invalid quoted field.");
      field += char;
      started = true;
    }
  }
  if (quoted) throw new Error("CSV contains an unclosed quoted field.");
  if (started || closed || record.length) endRecord();
  if (!records.length) throw new Error("CSV has no header.");
  const [columns, ...rows] = records;
  if (
    columns.some((column) => !column.trim()) ||
    new Set(columns).size !== columns.length
  )
    throw new Error("CSV headers must be nonempty and unique.");
  if (rows.some((row) => row.length !== columns.length))
    throw new Error("CSV rows have inconsistent column counts.");
  return { columns, rows };
}

export type RouteSummary = {
  route: string;
  observations: number;
  meanDelay: number;
  onTimeRate: number;
};
export type Analysis = {
  columns: string[];
  rowCount: number;
  routes: RouteSummary[] | null;
  recommendation: string;
  period: string | null;
};

export function analyzeCsv(bytes: ArrayBuffer): Analysis {
  const { columns, rows } = parseCsv(bytes);
  const required = [
    "observed_at",
    "route",
    "delay_minutes",
    "delivered_on_time",
  ];
  const indexes = required.map((column) => columns.indexOf(column));
  const fallback: Analysis = {
    columns,
    rowCount: rows.length,
    routes: null,
    period: null,
    recommendation:
      "Verified CSV available. This schema does not support the route comparison; inspect the schema and download the original file.",
  };
  if (indexes.some((index) => index < 0) || !rows.length) return fallback;
  const groups = new Map<
    string,
    { delays: number; onTime: number; count: number }
  >();
  const dates: string[] = [];
  for (const row of rows) {
    const [observed, route, delay, onTime] = indexes.map((index) => row[index]);
    if (
      !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(observed) ||
      Number.isNaN(Date.parse(observed)) ||
      !route.trim() ||
      !/^-?\d+(?:\.\d+)?$/.test(delay) ||
      !Number.isFinite(Number(delay)) ||
      !/^(true|false|1|0)$/i.test(onTime)
    )
      return {
        ...fallback,
        recommendation:
          "Verified CSV available. Route fields contain unsupported values, so no route recommendation was calculated.",
      };
    const group = groups.get(route) ?? { delays: 0, onTime: 0, count: 0 };
    group.delays += Number(delay);
    group.onTime += /^(true|1)$/i.test(onTime) ? 1 : 0;
    group.count += 1;
    if (!Number.isFinite(group.delays)) return fallback;
    groups.set(route, group);
    dates.push(observed.slice(0, 10));
  }
  const routes = [...groups].map(([route, group]) => ({
    route,
    observations: group.count,
    meanDelay: group.delays / group.count,
    onTimeRate: group.onTime / group.count,
  }));
  routes.sort(
    (a, b) =>
      a.meanDelay - b.meanDelay ||
      b.onTimeRate - a.onTimeRate ||
      (a.route < b.route ? -1 : a.route > b.route ? 1 : 0),
  );
  dates.sort();
  return {
    columns,
    rowCount: rows.length,
    routes,
    period: `${dates[0]} → ${dates[dates.length - 1]}`,
    recommendation: `Choose ${routes[0].route} in this dataset: lowest observed mean delay (${routes[0].meanDelay.toFixed(1)} minutes). Ties use higher on-time rate, then route name. This is a local descriptive calculation, not a forecast.`,
  };
}
