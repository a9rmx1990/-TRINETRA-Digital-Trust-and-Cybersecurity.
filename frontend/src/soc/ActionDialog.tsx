import { Copy, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, newKey } from "../lib/api";
import { soc, type CaseFile, type Proposal } from "./api";
import { ACTION_EFFECT, ACTION_LABEL } from "./ui";

export type DialogReq = { kind: "action"; action: string } | { kind: "review"; proposal: Proposal; decision: "approve" | "reject" };

const DESTRUCTIVE = new Set(["reject_transfer", "restrict_counterparty", "restrict_sender_account"]);

export function ActionDialog({ req, file, onClose, onDone, onStale }: {
  req: DialogReq; file: CaseFile; onClose: () => void; onDone: () => void; onStale: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(document.activeElement);
  const [rationale, setRationale] = useState("");
  const [label, setLabel] = useState<"fraud" | "legitimate" | "">("");
  const [restriction, setRestriction] = useState(file.restrictions[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const commandKey = useRef(newKey());
  const version = useRef(file.case.version);
  const hid = useId();
  const rid = useId();

  useEffect(() => {
    const d = ref.current;
    d?.showModal();
    const back = opener.current;
    return () => { d?.close(); (back as HTMLElement | null)?.focus?.(); };
  }, []);

  const action = req.kind === "action" ? req.action : req.proposal.action;
  const isReject = req.kind === "review" && req.decision === "reject";
  const title = req.kind === "review" ? `${isReject ? "Reject proposal" : "Approve proposal"}: ${ACTION_LABEL[action]}` : ACTION_LABEL[action];
  const stale = version.current !== file.case.version;
  const valid = rationale.trim().length >= 8 && (action !== "record_verdict" || isReject || !!label) &&
    (action !== "lift_restriction" || isReject || !!restriction);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const res = req.kind === "review"
        ? await soc.review(req.proposal.id, { decision: req.decision, expected_version: version.current, rationale, command_key: commandKey.current })
        : await soc.action(file.case.id, { action, expected_version: version.current, rationale, command_key: commandKey.current,
            params: action === "record_verdict" ? { label } : action === "lift_restriction" ? { restriction_id: restriction } : {} });
      onDone();
      if (res?.code) setCode(res.code);
      else onClose();
    } catch (e2) {
      const er = e2 instanceof ApiError ? e2 : new ApiError(0, "x", "The action failed.");
      setErr(er);
      if (er.code === "stale_version") onStale();
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} aria-labelledby={hid} onCancel={(e) => { e.preventDefault(); onClose(); }}
            className="ws-soc sheet-in m-0 ml-auto h-full max-h-none w-full max-w-md bg-soc-panel p-0 text-soc-ink backdrop:bg-[#050a12]/70 sm:border-l sm:border-soc-line">
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-soc-line px-5 py-4">
          <h2 id={hid} className="text-base font-semibold">{title}</h2>
          <button className="soc-btn-ghost p-1.5" onClick={onClose} aria-label="Close"><X className="h-4 w-4" aria-hidden /></button>
        </div>
        {code ? (
          <div className="flex-1 space-y-4 px-5 py-5">
            <p className="text-sm text-soc-muted">Read this code to the customer after confirming their identity on a trusted channel. It will not be shown again.</p>
            <div className="flex items-center justify-between rounded-md border border-soc-amber/60 bg-soc-canvas px-4 py-4">
              <span className="num font-mono text-3xl tracking-[0.35em] text-soc-amber" aria-label={`Code ${code.split("").join(" ")}`}>{code}</span>
              <button className="soc-btn-ghost" onClick={() => { navigator.clipboard?.writeText(code); setCopied(true); }}>
                <Copy className="h-4 w-4" aria-hidden />{copied ? "Copied" : "Copy"}
              </button>
            </div>
            <button className="soc-btn-primary w-full py-2" onClick={onClose} autoFocus>Done</button>
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-1 flex-col">
            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5 text-sm">
              <div>
                <p className="text-xs text-soc-muted">Effect</p>
                <p className="mt-1 text-soc-ink">{isReject ? "Marks the proposal rejected. No action is taken on the transfer." : ACTION_EFFECT[action]}</p>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded border border-soc-line bg-soc-canvas px-3 py-2.5">
                <dt className="text-soc-muted">Target</dt>
                <dd className="font-mono text-xs leading-5">{file.payment.id}</dd>
                <dt className="text-soc-muted">Transfer</dt>
                <dd className="num">{file.payment.amount_display} to {file.beneficiary.masked}</dd>
                <dt className="text-soc-muted">Case version</dt>
                <dd className="num">{version.current}{stale && <span className="ml-2 text-soc-amber">case has changed</span>}</dd>
                {req.kind === "review" && <><dt className="text-soc-muted">Proposed by</dt><dd>{req.proposal.created_by} · tier {req.proposal.tier}</dd></>}
              </dl>
              {req.kind === "review" && (
                <div><p className="text-xs text-soc-muted">Agent rationale</p><p className="mt-1">{req.proposal.rationale}</p></div>
              )}
              {action === "record_verdict" && !isReject && (
                <fieldset>
                  <legend className="mb-1.5 text-xs text-soc-muted">Verdict</legend>
                  <div className="flex gap-2">
                    {(["fraud", "legitimate"] as const).map((l) => (
                      <label key={l} className={`flex-1 cursor-pointer rounded border px-3 py-2 text-center capitalize ${label === l ? "border-soc-amber bg-soc-raised" : "border-soc-line"}`}>
                        <input type="radio" name="verdict" className="sr-only" checked={label === l} onChange={() => setLabel(l)} />{l}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
              {action === "lift_restriction" && !isReject && (
                <label className="block">
                  <span className="mb-1 block text-xs text-soc-muted">Restriction</span>
                  <select className="soc-input" value={restriction} onChange={(e) => setRestriction(e.target.value)}>
                    {file.restrictions.map((r) => <option key={r.id} value={r.id}>{r.scope_type}: {r.reason.slice(0, 50)}</option>)}
                  </select>
                </label>
              )}
              <div>
                <label htmlFor={rid} className="mb-1 block text-xs text-soc-muted">Rationale (required, recorded in the audit trail)</label>
                <textarea id={rid} className="soc-input min-h-[96px]" value={rationale} onChange={(e) => setRationale(e.target.value)}
                          maxLength={1000} autoFocus />
                <p className="mt-1 text-xs text-soc-faint">{rationale.trim().length < 8 ? "At least 8 characters." : `${rationale.length} / 1000`}</p>
              </div>
              {err && (
                <p role="alert" className="rounded border border-soc-red/50 bg-soc-red/10 px-3 py-2 text-soc-ink">
                  {err.message}{err.code === "stale_version" && " The case has been refreshed; review it before acting again."}
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-soc-line px-5 py-3">
              <button type="button" className="soc-btn-ghost" onClick={onClose}>Cancel</button>
              {err?.code === "stale_version" || stale ? (
                <button type="button" className="soc-btn-ghost" onClick={() => { version.current = file.case.version; setErr(null); }}>
                  Use latest version ({file.case.version})
                </button>
              ) : (
                <button type="submit" disabled={!valid || busy}
                        className={DESTRUCTIVE.has(action) && !isReject ? "soc-btn-danger" : "soc-btn-primary"}>
                  {busy ? "Applying…" : isReject ? "Reject proposal" : req.kind === "review" ? "Approve and apply" : ACTION_LABEL[action]}
                </button>
              )}
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
}
