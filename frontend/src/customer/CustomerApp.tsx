import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { navigate } from "../lib/router";
import { api, session, type Account, type Beneficiary } from "./api";
import { AddBeneficiaryForm, Beneficiaries } from "./Beneficiaries";
import { History } from "./History";
import { Transfer } from "./Transfer";
import { Field, Notice, Spinner } from "./ui";

type Me = { accounts: Account[]; beneficiaries: Beneficiary[] };

export function CustomerApp({ path }: { path: string }) {
  const [me, setMe] = useState<Me | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!session.token()) { setMe({ accounts: [], beneficiaries: [] }); return; }
    try {
      setMe(await api.me());
      setErr(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        session.clear();
        setMe({ accounts: [], beneficiaries: [] });
      } else setErr(e instanceof ApiError ? e.message : "Could not reach the sandbox.");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const account = me?.accounts[0];
  const section = path.startsWith("/history") ? "history" : path.startsWith("/beneficiaries") ? "contacts" : "request";
  const selectedPayment = path.startsWith("/history/") ? path.split("/")[2] : null;

  return (
    <div className="ws-customer min-h-screen bg-canvas text-ink">
      <a href="#main" className="sr-only-focusable fixed left-3 top-3 z-50 rounded bg-white px-3 py-2 text-sm font-semibold">Skip to content</a>
      <header className="workspace-bar">
        <div className="mx-auto flex min-h-16 max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 sm:px-6">
          <a href="/" onClick={(e) => { e.preventDefault(); navigate("/"); }} className="workspace-brand">
            Trinetra
          </a>
          <span className="border-l border-line pl-4 text-sm text-muted">Banking sandbox</span>
          {account && (
            <nav aria-label="Main" className="order-last flex w-full gap-1 sm:order-none sm:ml-auto sm:w-auto">
              {[["request", "/", "Request money"], ["contacts", "/beneficiaries", "Contacts"], ["history", "/history", "History"]].map(([k, href, label]) => (
                <a key={k} href={href} aria-current={section === k ? "page" : undefined}
                   onClick={(e) => { e.preventDefault(); navigate(href); }}
                   className={`inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-semibold transition-colors ${section === k ? "bg-primary-soft text-primary" : "text-muted hover:bg-canvas hover:text-ink"}`}>
                  {label}
                </a>
              ))}
            </nav>
          )}
        </div>
      </header>

      <main id="main" className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
        {err && <Notice tone="bad" title="The sandbox is not responding" action={<button className="btn-secondary" onClick={load}>Try again</button>}>{err}</Notice>}
        {!me && !err && <p className="flex items-center gap-2 text-muted"><Spinner />Loading</p>}
        {me && !account && <Onboarding onCreated={load} />}
        {me && account && section === "request" && (
          me.beneficiaries.length === 0 ? (
            <FirstBeneficiary account={account} onAdded={load} />
          ) : (
            <Transfer account={account} beneficiaries={me.beneficiaries} onAddBeneficiary={() => navigate("/beneficiaries")} onDone={() => undefined} />
          )
        )}
        {me && account && section === "contacts" && <Beneficiaries items={me.beneficiaries} onChange={load} />}
        {me && account && section === "history" && <History selected={selectedPayment} />}
      </main>
    </div>
  );
}

function Onboarding({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await session.ensure();
      await api.createAccount(name);
      onCreated();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace-wash grid gap-8 rounded-2xl border border-line px-5 py-8 sm:px-9 sm:py-12 md:grid-cols-[minmax(0,1fr)_minmax(280px,380px)] md:items-center lg:gap-12 lg:p-14">
      <div className="max-w-[34rem] space-y-5">
        <h1 className="workspace-title text-[clamp(2.15rem,5vw,3.6rem)] [text-wrap:balance]">Request money with a spoken confirmation</h1>
        <p className="max-w-[41ch] text-[1rem] leading-relaxed text-muted">
          Practice requesting money from a contact. A short voice confirmation helps the sandbox review your request.
        </p>
      </div>
      <form onSubmit={submit} className="workspace-panel space-y-5 p-5 sm:p-7">
        <h2 className="text-lg font-semibold">Open a sandbox account</h2>
        <Field label="Account name" hint="For example, Savings or Household.">
          {(p) => <input {...p} className="field-input" value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        {err && <Notice tone="bad">{err}</Notice>}
        <button type="submit" className="btn-primary w-full" disabled={busy || name.trim().length < 2}>
          {busy && <Spinner />}Create sandbox account
        </button>
        <p className="text-sm text-muted">No real money moves. Your session stays in this browser.</p>
      </form>
    </div>
  );
}

function FirstBeneficiary({ account, onAdded }: { account: Account; onAdded: () => void }) {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="space-y-2">
        <p className="text-sm text-muted">{account.display_name} · <span className="font-mono">{account.account_ref}</span></p>
        <h1 className="workspace-title text-3xl">Who are you requesting money from?</h1>
        <p className="text-base text-muted">Save a contact using their sandbox account reference.</p>
      </div>
      <AddBeneficiaryForm onAdded={onAdded} />
    </div>
  );
}
