import { ArrowDownLeft, ArrowLeft, ArrowUpRight, ChevronRight, ReceiptText } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { navigate } from "../lib/router";
import { api, type Receipt } from "./api";
import { ReceiptView } from "./Receipt";
import { Notice, Spinner, StateBadge } from "./ui";

export function History({ selected }: { selected: string | null }) {
  const [items, setItems] = useState<Receipt[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<Receipt | null>(null);

  const load = useCallback(async (before?: number) => {
    setLoading(true);
    setErr(null);
    try {
      const r = await api.payments(before);
      setItems((cur) => (before && cur ? [...cur, ...r.items] : r.items));
      setNext(r.next_before_ms);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load history.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    api.payment(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  if (selected && detail) {
    return (
      <div className="space-y-4">
        <button className="btn-quiet -ml-2" onClick={() => navigate("/history")}><ArrowLeft size={16} aria-hidden="true" />Back to history</button>
        <ReceiptView receipt={detail} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="workspace-title text-3xl">Request history</h1>
      {err && <Notice tone="bad" action={<button className="btn-secondary" onClick={() => load()}>Try again</button>}>{err}</Notice>}
      {items === null && !err && <p className="flex items-center gap-2 text-muted"><Spinner />Loading requests</p>}
      {items && items.length === 0 && (
        <div className="workspace-panel px-6 py-10 text-center">
          <span className="customer-list-icon mx-auto mb-3"><ReceiptText size={18} aria-hidden="true" /></span>
          <p className="font-semibold text-ink">No requests yet</p>
          <p className="mt-1 text-sm text-muted">Your submitted requests appear here with their current status.</p>
          <button className="btn-primary mt-4" onClick={() => navigate("/")}>Request money</button>
        </div>
      )}
      {items && items.length > 0 && (
        <ul className="workspace-panel divide-y divide-line">
          {items.map((p) => (
            <li key={p.payment_id}>
              <button className="customer-list-row hover:bg-canvas focus-visible:outline-offset-[-2px]"
                      onClick={() => navigate(`/history/${p.payment_id}`)}>
                <span className="customer-list-icon hidden sm:grid">{p.direction === "outgoing"
                  ? <ArrowUpRight size={18} aria-hidden="true" /> : <ArrowDownLeft size={18} aria-hidden="true" />}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-ink">{p.beneficiary_name}
                    <span className="ml-2 font-normal text-muted">{p.beneficiary_masked}</span></p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-muted">
                    <span className="num">{formatDateTime(p.created_ms)}</span><span>{p.channel}</span>
                    {p.direction === "outgoing" && <span>Outgoing transfer</span>}
                    <StateBadge state={p.state} direction={p.direction} />
                  </p>
                </div>
                <span className="num shrink-0 text-right text-base font-semibold text-ink">{p.amount_display}</span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      {next && (
        <button className="btn-secondary" onClick={() => load(next)} disabled={loading}>{loading && <Spinner />}Load older requests</button>
      )}
    </div>
  );
}
