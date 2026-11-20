/** Formatting and parsing shared by both workspaces. Pure functions, unit-tested with node --test. */

/** Indian digit grouping: 123456789 paise -> "₹12,34,567.89" */
export function formatINR(minor: number, opts: { symbol?: boolean; paise?: boolean } = {}): string {
  const { symbol = true, paise = true } = opts;
  const neg = minor < 0;
  const abs = Math.abs(Math.trunc(minor));
  const rupees = Math.floor(abs / 100);
  const p = abs % 100;
  let s = String(rupees);
  if (s.length > 3) {
    let head = s.slice(0, -3);
    const tail = s.slice(-3);
    const parts: string[] = [];
    while (head.length > 2) {
      parts.unshift(head.slice(-2));
      head = head.slice(0, -2);
    }
    if (head) parts.unshift(head);
    s = [...parts, tail].join(",");
  }
  const out = `${symbol ? "₹" : ""}${s}${paise ? "." + String(p).padStart(2, "0") : ""}`;
  return neg ? "-" + out : out;
}

export type ParsedAmount = { ok: true; minor: number } | { ok: false; error: string };

/** Parse a rupee amount typed by a person into integer paise. Accepts Indian or Western grouping. */
export function parseINR(input: string): ParsedAmount {
  const raw = input.replace(/[₹\s]/g, "").replace(/,/g, "");
  if (!raw) return { ok: false, error: "Enter an amount." };
  if (!/^\d+(\.\d{1,2})?$/.test(raw)) return { ok: false, error: "Use digits only, with up to two decimal places." };
  const [r, p = ""] = raw.split(".");
  if (r.length > 10) return { ok: false, error: "Amount is above the sandbox limit." };
  const minor = Number(r) * 100 + Number(p.padEnd(2, "0"));
  if (minor <= 0) return { ok: false, error: "Enter an amount greater than zero." };
  if (minor > 10_00_00_000_00) return { ok: false, error: "Amount is above the sandbox limit of ₹10,00,00,000." };
  return { ok: true, minor };
}

/** Live grouping while typing, preserving a trailing decimal point. */
export function groupWhileTyping(input: string): string {
  const cleaned = input.replace(/[^\d.]/g, "");
  const [r, ...rest] = cleaned.split(".");
  const dec = rest.length ? "." + rest.join("").slice(0, 2) : "";
  if (!r) return dec ? "0" + dec : "";
  const n = r.replace(/^0+(?=\d)/, "");
  return formatINR(Number(n) * 100, { symbol: false, paise: false }) + dec;
}

export function maskRef(ref: string): string {
  return ref ? "•••• " + ref.slice(-4) : "";
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function clockTime(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatDateTime(ms: number, tz?: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz,
  }).format(new Date(ms));
}

export function formatDay(ms: number, tz?: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: tz }).format(new Date(ms));
}

export function rate(n: number | null | undefined): string {
  return n == null ? "Unavailable" : `${(n * 100).toFixed(1)}%`;
}
