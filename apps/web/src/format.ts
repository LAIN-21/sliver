export function formatPrice(amountMinor: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amountMinor / 100);
}

const BPS_DENOMINATOR = 10_000;

/** A fee rate in basis points as a percentage: 1000 → "10%", 250 → "2.5%". */
export function formatBps(bps: number): string {
  return `${(bps / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
}

/**
 * The seller's net at a price, rounded like the server (apps/api/sliver_api/payments/fees.py):
 * Sliver's fee is rounded down to a whole cent and the net is the rest.
 */
export function netAfterFee(priceMinor: number, bps: number): number {
  return priceMinor - Math.floor((priceMinor * bps) / BPS_DENOMINATOR);
}

export function formatCategory(category: string): string {
  return category.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatRange(start: string, end: string): string {
  return start === end ? start : `${start} → ${end}`;
}

const DROPS_PER_XRP = 1_000_000;

export function formatAmount(value: string, asset: string): string {
  if (asset !== "XRP") return `${value} ${asset}`;
  const xrp = Number(value) / DROPS_PER_XRP;
  return `${xrp.toLocaleString("en-US", { maximumFractionDigits: 6 })} XRP`;
}

export function shortHash(hash: string, size = 6): string {
  return hash.length > size * 2 + 1 ? `${hash.slice(0, size)}…${hash.slice(-size)}` : hash;
}

export function formatNetwork(network: string): string {
  return network === "xrpl:1" ? "XRPL Testnet" : network;
}

export function formatLatency(ms: number): string {
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function formatAgo(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatClock(iso: string, millis = true): string {
  const date = new Date(iso);
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return millis ? `${time}.${String(date.getMilliseconds()).padStart(3, "0")}` : time;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}
