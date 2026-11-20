import { Trash2, UserPlus } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { api, type Beneficiary } from "./api";
import { Field, Notice, Spinner } from "./ui";

export function AddBeneficiaryForm({ onAdded, compact = false }: { onAdded: (b: Beneficiary) => void; compact?: boolean }) {
  const [name, setName] = useState("");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const b = await api.addBeneficiary(name, ref);
      setName("");
      setRef("");
      onAdded(b);
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2 : new ApiError(0, "x", "Could not save the contact."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className={`space-y-4 ${compact ? "" : "workspace-panel p-5"}`}>
      {!compact && <h2 className="text-lg font-semibold text-ink">Add contact</h2>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" hint="As you want to see it in history." error={err?.field === "display_name" ? err.message : null}>
          {(p) => <input {...p} className="field-input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" required />}
        </Field>
        <Field label="Sandbox account reference" hint="6 to 18 letters or digits." error={err?.field === "account_ref" ? err.message : null}>
          {(p) => <input {...p} className="field-input font-mono uppercase" value={ref} autoComplete="off" spellCheck={false}
                         onChange={(e) => setRef(e.target.value.toUpperCase())} required />}
        </Field>
      </div>
      {err && !err.field && <Notice tone="bad">{err.message}</Notice>}
      <button type="submit" className="btn-primary" disabled={busy || !name.trim() || !ref.trim()}>
        {busy ? <Spinner /> : <UserPlus className="h-4 w-4" aria-hidden />}Add contact
      </button>
    </form>
  );
}

export function Beneficiaries({ items, onChange }: { items: Beneficiary[]; onChange: () => void }) {
  const [removing, setRemoving] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  async function remove(id: string) {
    setRemoving(id);
    try { await api.removeBeneficiary(id); onChange(); } finally { setRemoving(null); setConfirm(null); }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="workspace-title text-3xl">Contacts</h1>
      {items.length === 0 ? (
        <p className="text-base text-[#3A4458]">Add the person or business you want to request money from.</p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-white">
          {items.map((b) => (
            <li key={b.id} className="flex items-center gap-4 px-4 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-ink">{b.display_name}</p>
                <p className="text-sm text-muted">{b.account_ref_masked} · added {formatDateTime(b.created_ms)}</p>
              </div>
              {confirm === b.id ? (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-ink">Remove?</span>
                  <button className="btn-secondary px-3 py-1.5 text-sm text-bad" onClick={() => remove(b.id)} disabled={removing === b.id}>Remove</button>
                  <button className="btn-quiet text-sm" onClick={() => setConfirm(null)}>Keep</button>
                </div>
              ) : (
                <button className="btn-quiet text-muted hover:text-bad" onClick={() => setConfirm(b.id)} aria-label={`Remove ${b.display_name}`}>
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <AddBeneficiaryForm onAdded={onChange} />
    </div>
  );
}
