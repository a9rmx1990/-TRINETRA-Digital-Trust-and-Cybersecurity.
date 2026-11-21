import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, newKey } from "../lib/api";
import { formatINR, groupWhileTyping, parseINR } from "../lib/format";
import { api, type Account, type Beneficiary, type Receipt } from "./api";
import { ReceiptView } from "./Receipt";
import { Field, Notice, Spinner } from "./ui";
import { useRecorder } from "./useRecorder";
import { VoiceStep } from "./VoiceStep";

type Step = "details" | "voice" | "review" | "receipt";
type Draft = { beneficiary_id: string; amount: string; channel: string; remark: string };
const CHANNELS = [
  { v: "IMPS", label: "IMPS", hint: "Instant, any time" },
  { v: "UPI", label: "UPI", hint: "Instant, any time" },
  { v: "NEFT", label: "NEFT", hint: "Settles in batches" },
  { v: "RTGS", label: "RTGS", hint: "₹2,00,000 and above" },
];
const DRAFT_KEY = "trinetra.customer.draft";

function loadDraft(): Draft {
  try {
    const d = sessionStorage.getItem(DRAFT_KEY);
    if (d) return JSON.parse(d);
  } catch { /* ignore */ }
  return { beneficiary_id: "", amount: "", channel: "IMPS", remark: "" };
}

const STEPS: { id: Step; label: string }[] = [
  { id: "details", label: "Details" }, { id: "voice", label: "Voice" }, { id: "review", label: "Review" },
];

function Stepper({ step }: { step: Step }) {
  const idx = step === "receipt" ? 3 : STEPS.findIndex((s) => s.id === step);
  return (
    <ol className="request-steps" aria-label="Request progress">
      {STEPS.map((s, i) => (
        <li key={s.id} aria-current={i === idx ? "step" : undefined} data-complete={i < idx}>
          <span className="request-step-index">
            {i < idx ? <Check className="h-3.5 w-3.5" aria-hidden /> : i + 1}
          </span>
          <span>{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

export function Transfer({ account, beneficiaries, onAddBeneficiary, onDone }: {
  account: Account; beneficiaries: Beneficiary[]; onAddBeneficiary: () => void; onDone: (r: Receipt) => void;
}) {
  const [step, setStep] = useState<Step>("details");
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitErr, setSubmitErr] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const keyRef = useRef<string | null>(null);
  const rec = useRecorder();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* ignore */ }
  }, [draft]);
  useEffect(() => { headingRef.current?.focus(); }, [step]);

  const benef = beneficiaries.find((b) => b.id === draft.beneficiary_id);
  const parsed = useMemo(() => parseINR(draft.amount), [draft.amount]);
  const amountText = parsed.ok ? formatINR(parsed.minor) : "";

  function validate(): boolean {
    const e: Record<string, string> = {};
    if (!benef) e.beneficiary = "Choose who you want to request money from.";
    if (!parsed.ok) e.amount = parsed.error;
    else if (draft.channel === "RTGS" && parsed.minor < 2_00_000_00) e.channel = "RTGS is for ₹2,00,000 and above. Choose IMPS, UPI or NEFT.";
    if (draft.remark.length > 140) e.remark = "Keep the remark under 140 characters.";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function cancel() {
    rec.reset();
    keyRef.current = null;
    setStep("details");
  }

  async function submit() {
    if (!parsed.ok || !benef || !rec.call) return;
    keyRef.current ??= newKey(); // one attempt keeps one key across retries
    setSubmitting(true);
    setSubmitErr(null);
    try {
      const r = await api.requestMoney(keyRef.current, {
        account_id: account.id, beneficiary_id: benef.id, amount_minor: parsed.minor, channel: draft.channel,
        remark: draft.remark.trim() || null, call_id: rec.call.id });
      finish(r);
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "network", "Unknown error");
      if (["capture_expired", "capture_unusable", "capture_already_used", "capture_not_found", "capture_unfinished"].includes(err.code)) {
        rec.reset();
        keyRef.current = null;
        setStep("voice");
      }
      setSubmitErr(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function checkStatus() {
    if (!keyRef.current) return;
    setSubmitting(true);
    try {
      finish(await api.lookup(keyRef.current));
    } catch (e) {
      setSubmitErr(e instanceof ApiError && e.status === 404
        ? new ApiError(404, "not_recorded", "No request was recorded for that attempt. You can submit again safely.")
        : (e as ApiError));
    } finally {
      setSubmitting(false);
    }
  }

  function finish(r: Receipt) {
    setReceipt(r);
    setStep("receipt");
    setDraft({ beneficiary_id: "", amount: "", channel: "IMPS", remark: "" });
    keyRef.current = null;
    onDone(r);
  }

  if (step === "receipt" && receipt) {
    return <ReceiptView receipt={receipt} onNew={() => { rec.reset(); setReceipt(null); setStep("details"); }} />;
  }

  const summary = (
    <aside className="lg:sticky lg:top-6" aria-label="Request summary">
      <div className="workspace-panel overflow-hidden">
        <div className="workspace-dark space-y-2 p-5">
          <h2 className="text-sm font-semibold">Request summary</h2>
          <p className="num break-words text-3xl font-semibold tracking-tight">{amountText || "—"}</p>
        </div>
        <dl className="divide-y divide-line px-5 py-2 text-base">
          <Row k="Requested from" v={benef ? <>{benef.display_name}<span className="block text-sm text-muted">{benef.account_ref_masked}</span></> : <span className="text-muted">Not chosen</span>} />
          <Row k="Your account" v={<>{account.display_name}<span className="block text-sm text-muted">{account.account_ref_masked}</span></>} />
          <Row k="Channel" v={draft.channel} />
          <Row k="Voice" v={rec.phase === "ready" ? <span className="text-ok">Accepted</span> : <span className="text-muted">Not recorded</span>} />
        </dl>
      </div>
    </aside>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-10">
      <div className="min-w-0 space-y-6">
        <div className="space-y-4">
          <h1 ref={headingRef} tabIndex={-1} className="workspace-title text-3xl focus:outline-none">Request money</h1>
          <Stepper step={step} />
        </div>

        {step === "details" && (
          <form className="workspace-panel space-y-5 p-4 sm:p-6" noValidate onSubmit={(e) => { e.preventDefault(); if (validate()) setStep("voice"); }}>
            {beneficiaries.length === 0 ? (
              <Notice title="Add a contact first" action={<button type="button" className="btn-primary" onClick={onAddBeneficiary}>Add contact</button>} />
            ) : (
              <Field label="Request from" error={errors.beneficiary}>
                {(p) => (
                  <select {...p} className="field-input" value={draft.beneficiary_id}
                          onChange={(e) => setDraft({ ...draft, beneficiary_id: e.target.value })}>
                    <option value="">Choose a contact</option>
                    {beneficiaries.map((b) => <option key={b.id} value={b.id}>{b.display_name} ({b.account_ref_masked})</option>)}
                  </select>
                )}
              </Field>
            )}
            <Field label="Amount" hint="In rupees. Up to two decimal places." error={errors.amount}>
              {(p) => (
                <div className="relative max-w-xs">
                  <span className="pointer-events-none absolute inset-y-0 left-3 grid place-items-center text-muted" aria-hidden>₹</span>
                  <input {...p} inputMode="decimal" autoComplete="off" className="field-input num min-h-14 pl-8 text-xl font-semibold"
                         value={draft.amount} placeholder="0.00"
                         onChange={(e) => setDraft({ ...draft, amount: groupWhileTyping(e.target.value) })} />
                </div>
              )}
            </Field>
            <fieldset className="space-y-1.5">
              <legend className="text-sm font-semibold text-ink">Channel</legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {CHANNELS.map((c) => (
                  <label key={c.v} className={`cursor-pointer rounded-lg border px-3 py-2 transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary ${
                    draft.channel === c.v ? "border-primary bg-primary-soft" : "border-line bg-white hover:border-primary"}`}>
                    <input type="radio" name="channel" value={c.v} className="sr-only" checked={draft.channel === c.v}
                           onChange={() => setDraft({ ...draft, channel: c.v })} />
                    <span className="block text-sm font-semibold text-ink">{c.label}</span>
                    <span className="block text-xs text-muted">{c.hint}</span>
                  </label>
                ))}
              </div>
              {errors.channel && <p className="text-sm text-bad">{errors.channel}</p>}
            </fieldset>
            <Field label="Remark (optional)" hint="Shown to you in history. Up to 140 characters." error={errors.remark}>
              {(p) => <input {...p} className="field-input" maxLength={140} value={draft.remark}
                             onChange={(e) => setDraft({ ...draft, remark: e.target.value })} />}
            </Field>
            <div className="flex justify-end border-t border-line pt-4">
              <button type="submit" className="btn-primary" disabled={beneficiaries.length === 0}>Continue to voice confirmation<ArrowRight size={16} aria-hidden="true" /></button>
            </div>
          </form>
        )}

        {step === "voice" && (
          <>
            {submitErr && <Notice tone="warn" title="Record again">{submitErr.message}</Notice>}
            <button type="button" className="btn-quiet -ml-2" onClick={() => setStep("details")} disabled={rec.phase === "recording"}>
              <ArrowLeft className="h-4 w-4" aria-hidden />Edit details
            </button>
            <VoiceStep rec={rec} onCancel={cancel} onContinue={() => { setSubmitErr(null); setStep("review"); }}
                       contactName={benef?.display_name ?? ""} amountText={amountText} purpose={draft.remark} />
          </>
        )}

        {step === "review" && benef && parsed.ok && (
          <div className="workspace-panel space-y-5 p-4 sm:p-6">
            <p className="text-base text-muted">Check the details before you submit.</p>
            <div className="overflow-hidden rounded-lg border border-line bg-white">
              <div className="customer-amount border-b border-line">
                <span className="text-sm text-muted">Amount requested</span>
                <span className="num text-3xl font-semibold tracking-tight text-ink">{formatINR(parsed.minor)}</span>
              </div>
              <dl className="divide-y divide-line px-5 text-base">
                <Row k="Requested from" v={<>{benef.display_name} <span className="text-muted">{benef.account_ref_masked}</span></>} />
                <Row k="Your account" v={<>{account.display_name} <span className="text-muted">{account.account_ref_masked}</span></>} />
                <Row k="Channel" v={draft.channel} />
                {draft.remark.trim() && <Row k="Remark" v={draft.remark.trim()} />}
              </dl>
            </div>
            {submitErr && (
              submitErr.isNetwork ? (
                <Notice tone="warn" title="We could not confirm the request"
                        action={<button className="btn-secondary" onClick={checkStatus} disabled={submitting}>Check status</button>}>
                  The connection dropped before the bank replied. Check the status before submitting a duplicate request.
                </Notice>
              ) : <Notice tone={submitErr.code === "not_recorded" ? "info" : "bad"}>{submitErr.message}</Notice>
            )}
            <div className="flex flex-wrap justify-between gap-2 border-t border-line pt-4">
              <button type="button" className="btn-secondary" onClick={() => setStep("details")} disabled={submitting}>Edit details</button>
              <button type="button" className="btn-primary min-w-[10rem]" onClick={submit}
                      disabled={submitting || rec.phase !== "ready"}>
                {submitting ? <><Spinner />Submitting</> : `Request ${formatINR(parsed.minor)}`}
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="hidden lg:block">{summary}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="min-w-0 break-words text-right text-ink">{v}</dd>
    </div>
  );
}
