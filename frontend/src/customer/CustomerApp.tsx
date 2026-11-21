import { ArrowDownLeft, BookOpen, ContactRound, Mic, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { navigate } from "../lib/router";
import { Brand } from "../ui/Brand";
import { api, session, type Account, type Beneficiary } from "./api";
import { AddBeneficiaryForm, Beneficiaries } from "./Beneficiaries";
import { History } from "./History";
import { Transfer } from "./Transfer";
import { Field, Notice, Spinner } from "./ui";

type Me = { accounts: Account[]; beneficiaries: Beneficiary[] };
const navigation = [
  { id: "request", href: "/", label: "Request money", Icon: ArrowDownLeft },
  { id: "contacts", href: "/beneficiaries", label: "Contacts", Icon: ContactRound },
  { id: "history", href: "/history", label: "History", Icon: BookOpen },
] as const;

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
        <div className="mx-auto flex min-h-[4.5rem] max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 sm:px-6">
          <Brand />
          <span className="border-l border-line pl-3 text-sm text-muted">Banking sandbox</span>
          {account && (
            <nav aria-label="Main" className="flex w-full flex-wrap gap-1 border-t border-line pt-2 sm:ml-auto sm:w-auto sm:border-0 sm:pt-0">
              {navigation.map(({ id, href, label, Icon }) => (
                <a key={id} href={href} aria-current={section === id ? "page" : undefined}
                   onClick={(e) => { e.preventDefault(); navigate(href); }}
                   className="customer-nav-link">
                  <Icon size={16} aria-hidden="true" className="hidden min-[380px]:block" />{label}
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
    <div className="workspace-entry">
      <div className="workspace-dark workspace-entry-intro">
        <Mic size={28} aria-hidden="true" />
        <div className="space-y-4">
          <h1 className="workspace-title max-w-[15ch] text-[clamp(2rem,4vw,3.25rem)] [text-wrap:balance]">Request money with a spoken confirmation</h1>
          <p className="max-w-[39ch] text-base">A short voice confirmation helps the sandbox review your request.</p>
        </div>
        <p className="flex items-center gap-2 border-t border-white/20 pt-4 text-sm"><ShieldCheck size={17} aria-hidden="true" />No real money moves.</p>
      </div>
      <form onSubmit={submit} className="workspace-entry-form">
        <h2 className="workspace-title text-2xl">Open a sandbox account</h2>
        <Field label="Account name" hint="For example, Savings or Household.">
          {(p) => <input {...p} className="field-input" value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        {err && <Notice tone="bad">{err}</Notice>}
        <button type="submit" className="btn-primary w-full" disabled={busy || name.trim().length < 2}>
          {busy && <Spinner />}Create sandbox account
        </button>
        <p className="text-sm text-muted">Your session stays in this browser.</p>
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
