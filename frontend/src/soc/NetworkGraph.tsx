import cytoscape, { type Core } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { formatDateTime, formatINR } from "../lib/format";
import { ChartFrame, Th } from "./ui";

type Transfer = { payment_id: string | null; settlement_id?: string; amount_minor: number; created_ms: number; proposed?: boolean };
type G = { nodes: { id: string; kind: string; label: string; is_sender: boolean; is_recipient: boolean }[];
           edges: { source: string; target: string; transfers: Transfer[]; proposed: boolean }[];
           truncated: boolean; window_days: number; max_depth: number; as_of_ms: number;
           features: { recent_distinct_other_senders: number; prior_settled_from_owner: number; inbound_settled_total: number } };

/** Directed recipient graph from the case's bounded, settled history. The proposed transfer is drawn separately. */
export function NetworkGraph({ graph, evidenceId, tz }: { graph: G | null; evidenceId?: string; tz: string }) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const reduce = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  const elements = useMemo(() => {
    if (!graph) return [];
    return [
      ...graph.nodes.map((n) => ({ data: { id: n.id, label: n.is_sender ? `Sender ${n.label}` : n.is_recipient ? `Recipient ${n.label}` : n.label,
                                           role: n.is_sender ? "sender" : n.is_recipient ? "recipient" : n.kind } })),
      ...graph.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, proposed: e.proposed ? 1 : 0,
                                              w: Math.min(6, 1 + e.transfers.length), n: e.transfers.length } })),
    ];
  }, [graph]);

  useEffect(() => {
    if (!box.current || !graph) return;
    cy.current?.destroy();
    const c = cytoscape({
      container: box.current, elements, autoungrabify: false, boxSelectionEnabled: false, wheelSensitivity: 0.2,
      style: [
        { selector: "node", style: { "background-color": "#DEF3FF", "border-color": "#526A81", "border-width": 1.5, label: "data(label)",
          color: "#0D263C", "font-size": 10, "text-valign": "bottom", "text-margin-y": 6, width: 22, height: 22, "font-family": "Public Sans" } },
        { selector: "node[role = 'sender']", style: { shape: "round-rectangle", "border-color": "#0D263C", "border-width": 2 } },
        { selector: "node[role = 'recipient']", style: { shape: "diamond", "border-color": "#00639A", "border-width": 2, width: 28, height: 28 } },
        { selector: "node[role = 'cp']", style: { shape: "diamond" } },
        { selector: "edge", style: { width: "data(w)", "line-color": "#526A81", "target-arrow-color": "#526A81", "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.8 } },
        { selector: "edge[proposed = 1]", style: { "line-style": "dashed", "line-color": "#00639A", "target-arrow-color": "#00639A", width: 2 } },
        { selector: ":selected", style: { "border-color": "#00639A", "border-width": 3, "line-color": "#0D263C", "target-arrow-color": "#0D263C" } },
      ],
      layout: { name: "cose", animate: !reduce, animationDuration: 300, padding: 24, nodeRepulsion: () => 9000, idealEdgeLength: () => 90 } as any,
    });
    c.one("layoutstop", () => c.fit(undefined, 36));
    c.on("tap", "node,edge", (ev) => setSel(ev.target.id()));
    c.on("tap", (ev) => { if (ev.target === c) setSel(null); });
    cy.current = c;
    setSel(null);
    return () => { c.destroy(); cy.current = null; };
  }, [elements, graph, reduce]);

  if (!graph) return null;

  const selEdges = sel ? graph.edges.filter((e, i) => `e${i}` === sel || e.source === sel || e.target === sel) : [];
  const allTransfers = graph.edges.flatMap((e) => e.transfers.map((t) => ({ ...t, source: e.source, target: e.target, proposed: e.proposed })));
  const label = (id: string) => graph.nodes.find((n) => n.id === id)?.label ?? id;

  const table = (
    <div className="max-h-64 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-soc-panel"><tr><Th>From</Th><Th>To</Th><Th>Payment</Th><Th right>Amount</Th><Th>Time</Th><Th>Kind</Th></tr></thead>
        <tbody>
          {allTransfers.map((t, i) => (
            <tr key={i} className="border-t border-soc-line/60">
              <td className="px-2 py-1">{label(t.source)}</td><td className="px-2 py-1">{label(t.target)}</td>
              <td className="px-2 py-1 font-mono text-xs">{t.payment_id ?? "this transfer"}</td>
              <td className="num px-2 py-1 text-right">{formatINR(t.amount_minor)}</td>
              <td className="num px-2 py-1">{formatDateTime(t.created_ms, tz)}</td>
              <td className="px-2 py-1">{t.proposed ? "Proposed" : "Settled"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const f = graph.features;
  return (
    <ChartFrame title="Recipient network"
      description={`Settled transfers within ${graph.window_days} days, up to ${graph.max_depth} hops. Dashed amber is the transfer under review.`}
      aside={graph.truncated ? <span className="text-xs text-soc-amber">Search depth truncated</span> : undefined}
      table={table}
      chart={
        <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
          <div ref={box} className="h-64 rounded border border-soc-line bg-soc-canvas" role="img"
               aria-label={`${graph.nodes.length} accounts and ${allTransfers.length} transfers. Use Show table for the list.`} />
          <div className="space-y-3 text-sm">
            <dl className="num grid grid-cols-[1fr_auto] gap-y-1 text-xs">
              <dt className="text-soc-muted">Other senders, 7 days</dt><dd className={f.recent_distinct_other_senders >= 3 ? "text-soc-red" : ""}>{f.recent_distinct_other_senders}</dd>
              <dt className="text-soc-muted">Prior settled from this customer</dt><dd>{f.prior_settled_from_owner}</dd>
              <dt className="text-soc-muted">Inbound settled total</dt><dd>{f.inbound_settled_total}</dd>
            </dl>
            {allTransfers.length <= 1 && <p className="text-xs text-soc-muted">No settled history around this recipient. A new beneficiary can legitimately have none.</p>}
            {sel ? (
              <div className="rounded border border-soc-line p-2">
                <p className="mb-1 text-xs text-soc-muted">Supporting transfers</p>
                <ul className="max-h-36 space-y-1 overflow-auto text-xs">
                  {selEdges.flatMap((e) => e.transfers).map((t, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span className="font-mono">{t.payment_id ? t.payment_id.slice(-10) : "proposed"}</span>
                      <span className="num text-soc-muted">{formatDateTime(t.created_ms, tz)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : <p className="text-xs text-soc-faint">Select an account or edge to see the transfers behind it.</p>}
            {evidenceId && <p className="font-mono text-[11px] text-soc-faint">evidence {evidenceId}</p>}
          </div>
        </div>
      } />
  );
}
