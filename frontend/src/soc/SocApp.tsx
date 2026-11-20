import { ArrowDown, ArrowUp, LogOut, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { formatDateTime, formatDuration, rate } from "../lib/format";
import { navigate, setQuery } from "../lib/router";
import { soc, socSession, type Analytics, type BucketRows, type CaseFile, type ModelInfo, type Notice, type Queue } from "./api";
import { CaseFileView } from "./CaseFile";
import { QualityAndWorker, QueueAgeChart, ReviewTime, VolumeChart } from "./charts";
import { DataState, DECISION_LABEL, PayState, Severity, Th, type QueryState } from "./ui";
import { useStream, type ConnState } from "./useStream";

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const TZ_OFFSET = -new Date().getTimezoneOffset();
const RANGES: Record<string, { label: string; ms: number }> = {
  "24h": { label: "Last 24 hours", ms: 86_400_000 }, "7d": { label: "Last 7 days", ms: 7 * 86_400_000 },
  "30d": { label: "Last 30 days", ms: 30 * 86_400_000 },
};
const AGE_WINDOWS: Record<string, [number, number | null]> = {
  lt_1h: [0, 3_600_000], "1h_4h": [3_600_000, 14_400_000], "4h_24h": [14_400_000, 86_400_000], gt_24h: [86_400_000, null],
};
const PRIO_SEV: Record<string, string> = { "1": "high", "2": "medium", "3": "low" };

export function SocApp({ path, search }: { path: string; search: string }) {
  const [sess, setSess] = useState(socSession.get());
  if (!sess) return <Login onIn={(s) => { socSession.set(s); setSess(s); }} />;
  return <Workspace path={path} search={search} name={sess.name} onOut={() => { socSession.set(null); setSess(null); }} />;
}

function Login({ onIn }: { onIn: (s: { token: string; name: string }) => void }) {
  const [name, setName] = useState("");
  const [pass, setPass] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await soc.login(name.trim(), pass);
      onIn({ token: r.token, name: name.trim() });
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Sign-in failed.");
    } finally { setBusy(false); }
  }
  return (
    <div className="ws-soc flex min-h-screen flex-col text-soc-ink">
      <header className="workspace-bar">
        <div className="mx-auto flex min-h-16 max-w-[1436px] items-center gap-4 px-4 sm:px-10">
          <span className="workspace-brand">Trinetra</span>
          <span className="border-l border-line pl-4 text-sm text-muted">Security operations</span>
        </div>
      </header>
      <main className="workspace-wash grid flex-1 place-items-center px-4 py-8">
        <form onSubmit={submit} className="workspace-panel w-full max-w-[420px] space-y-4 p-6 sm:p-9">
          <h1 className="workspace-title pb-2 text-2xl">SOC sign-in</h1>
          <label className="block text-sm font-semibold"><span className="mb-1.5 block text-soc-muted">Analyst name</span>
            <input className="soc-input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" required /></label>
          <label className="block text-sm font-semibold"><span className="mb-1.5 block text-soc-muted">Passcode</span>
            <input className="soc-input" type="password" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="current-password" required /></label>
          {err && <p role="alert" className="text-sm text-soc-red">{err}</p>}
          <button className="btn-primary w-full" disabled={busy || name.trim().length < 2 || !pass}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </main>
    </div>
  );
}

function ConnBadge({ s }: { s: ConnState }) {
  const m = { live: ["Live", "bg-soc-slate"], connecting: ["Connecting", "bg-soc-amber"], reconnecting: ["Reconnecting", "bg-soc-amber"],
              offline: ["Offline", "bg-soc-red"], unauthorized: ["Signed out", "bg-soc-red"] }[s];
  return <span className="inline-flex items-center gap-1.5" role="status"><span className={`h-2 w-2 rounded-full ${m[1]}`} aria-hidden />{m[0]}</span>;
}

function useQueryParams(search: string) {
  return useMemo(() => {
    const q = new URLSearchParams(search);
    return { range: RANGES[q.get("range") ?? ""] ? q.get("range")! : "7d", state: q.get("state") ?? "needs_action",
             sev: q.get("sev") ?? "", sort: q.get("sort") ?? "priority", caseId: q.get("case"), age: q.get("age"),
             view: q.get("view") ?? "queue" };
  }, [search]);
}

function Workspace({ path, search, name, onOut }: { path: string; search: string; name: string; onOut: () => void }) {
  const p = useQueryParams(search);
  const mobileCase = path.startsWith("/soc/case/") ? path.split("/")[3] : null;
  const selected = mobileCase ?? p.caseId;
  const [bounds, setBounds] = useState(() => { const now = Date.now(); return { from: now - RANGES[p.range].ms, to: now }; });
  const [queue, setQueue] = useState<Queue | null>(null);
  const [qState, setQState] = useState<QueryState>("loading");
  const [an, setAn] = useState<Analytics | null>(null);
  const [anState, setAnState] = useState<QueryState>("loading");
  const [file, setFile] = useState<CaseFile | null>(null);
  const [fileState, setFileState] = useState<QueryState>("loading");
  const [fileStale, setFileStale] = useState(false);
  const [lastOk, setLastOk] = useState<number | null>(null);
  const [me, setMe] = useState<{ tier: number; kill_switch: boolean } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wide = useWide();

  useEffect(() => { soc.me().then(setMe).catch(() => undefined); }, []);

  // Bounds are fixed per refresh so every widget shares the same window and watermark.
  const recomputeBounds = useCallback(() => { const now = Date.now(); setBounds({ from: now - RANGES[p.range].ms, to: now }); }, [p.range]);
  useEffect(() => { recomputeBounds(); }, [recomputeBounds]);

  const qparams = useMemo(() => {
    const q = new URLSearchParams({ sort: p.sort, limit: "100" });
    let from = bounds.from, to = bounds.to;
    if (p.age && AGE_WINDOWS[p.age]) {
      const [lo, hi] = AGE_WINDOWS[p.age];
      to = Math.min(to, bounds.to - lo);
      from = hi == null ? bounds.from : Math.max(bounds.from, bounds.to - hi);
    }
    q.set("from_ms", String(from));
    q.set("to_ms", String(Math.max(to, from + 1)));
    if (p.state !== "all") q.set("state", p.state);
    if (p.sev) q.set("severity", p.sev);
    return q;
  }, [bounds, p]);

  const loadQueue = useCallback(async () => {
    try {
      const [qq, aa] = await Promise.all([soc.queue(qparams), soc.analytics(bounds.from, bounds.to, TZ_OFFSET)]);
      setQueue(qq); setQState(qq.items.length ? "ok" : "empty");
      setAn(aa); setAnState("ok");
      setLastOk(Date.now());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setQState("unauthorized"); setAnState("unauthorized"); onOut(); return; }
      setQState((s) => (queue ? "stale" : s === "loading" ? "failed" : "failed"));
      setAnState(an ? "stale" : "failed");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qparams, bounds]);
  useEffect(() => { loadQueue(); }, [loadQueue]);

  const loadCase = useCallback(async (id: string) => {
    try {
      setFile(await soc.caseFile(id));
      setFileState("ok");
      setFileStale(false);
    } catch (e) {
      setFileState(e instanceof ApiError && e.status === 404 ? "empty" : e instanceof ApiError && e.status === 401 ? "unauthorized" : "failed");
    }
  }, []);
  useEffect(() => {
    setFile(null);  // switching case clears prior evidence immediately
    setFileStale(false);
    if (selected) { setFileState("loading"); loadCase(selected); }
  }, [selected, loadCase]);

  const dialogOpen = useRef(false);
  const fileVersion = useRef<number | null>(null);
  fileVersion.current = file?.case.version ?? null;
  const onNotices = useCallback((ns: Notice[]) => {
    loadQueue();
    if (!selected || fileVersion.current == null) return;
    const newer = ns.some((n) => n.case_id === selected && n.case_version > fileVersion.current!);
    if (!newer) return;
    // Never swap data under an open action drawer; otherwise refresh in place without moving focus.
    if (dialogOpen.current) setFileStale(true);
    else loadCase(selected);
  }, [loadQueue, loadCase, selected]);
  const { state: conn } = useStream(onNotices);
  const prevConn = useRef(conn);
  useEffect(() => { if (prevConn.current !== "live" && conn === "live") loadQueue(); prevConn.current = conn; }, [conn, loadQueue]);

  // Preserve queue scroll across refreshes.
  useLayoutEffect(() => {
    const y = Number(sessionStorage.getItem("trinetra.soc.scroll") || 0);
    if (scrollRef.current && y) scrollRef.current.scrollTop = y;
  }, [queue]);

  const openCase = (id: string) => {
    if (wide) setQuery({ case: id });
    else navigate(`/soc/case/${id}${search}`);
  };

  const header = (
    <header className="workspace-bar">
      <div className="mx-auto flex min-h-16 max-w-[1436px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 sm:px-10">
        <a href="/soc" onClick={(e) => { e.preventDefault(); navigate("/soc"); }} className="workspace-brand">Trinetra</a>
        <span className="border-l border-line pl-4 text-sm text-muted">Security operations</span>
        <nav aria-label="SOC views" className="order-last flex w-full gap-2 sm:order-none sm:ml-auto sm:w-auto">
          {[["queue", "Cases"], ["analytics", "Analytics"]].map(([k, l]) => (
            <button key={k} aria-current={p.view === k ? "page" : undefined} onClick={() => setQuery({ view: k === "queue" ? null : k }, false)}
                    className={`min-h-11 rounded-lg px-3 text-sm font-semibold ${p.view === k ? "bg-primary-soft text-primary" : "text-muted hover:bg-canvas hover:text-ink"}`}>{l}</button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 sm:ml-0">
          <span className="hidden text-sm text-muted md:inline">{name}</span>
          <button className="soc-btn-ghost min-h-11 min-w-11" onClick={onOut} aria-label="Sign out"><LogOut className="h-4 w-4" aria-hidden /></button>
        </div>
      </div>
    </header>
  );

  const casePane = !selected ? (
    <div className="grid h-full place-items-center p-8 text-center text-sm text-soc-muted">
      <p>Select a case to open its file.</p>
    </div>
  ) : file && file.case.id === selected ? (
    <CaseFileView file={file} stale={fileStale} tz={TZ} onRefresh={() => loadCase(selected)}
                  onDialogChange={(o) => { dialogOpen.current = o; }}
                  onBack={mobileCase ? () => navigate(`/soc${search}`) : undefined} />
  ) : <div className="p-4"><DataState state={fileState === "ok" ? "loading" : fileState} onRetry={() => loadCase(selected)} emptyText="Case not found in your scope." /></div>;

  return (
    <div className="ws-soc flex min-h-screen flex-col bg-soc-canvas text-soc-ink">
      {header}
      <div className="mx-auto flex w-full max-w-[1436px] flex-wrap items-end justify-between gap-4 px-4 py-6 sm:px-10 sm:py-9">
        <div>
          <h1 className="workspace-title text-[clamp(2.1rem,4vw,3rem)]">{p.view === "analytics" ? "Payment analytics" : "Case queue"}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span>Sandbox{me && <> · Tier {me.tier}{me.kill_switch && <span className="text-soc-red"> · Agent actions off</span>}</>}</span>
            <ConnBadge s={conn} />
            <span className="num">Updated {lastOk ? formatDateTime(lastOk, TZ) : "never"} · {TZ}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm font-semibold text-muted">Range
            <select className="soc-input !w-auto" value={p.range} onChange={(e) => setQuery({ range: e.target.value })}>
              {Object.entries(RANGES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select></label>
          <button className="soc-btn-ghost min-h-11 bg-white" onClick={() => { recomputeBounds(); if (selected) loadCase(selected); }} aria-label="Refresh now">
            <RefreshCw className="h-4 w-4" aria-hidden /> Refresh
          </button>
        </div>
      </div>
      {mobileCase && !wide ? (
        <main className="p-4">{casePane}</main>
      ) : p.view === "analytics" ? (
        <AnalyticsView an={an} state={anState} bounds={bounds} onRetry={loadQueue}
                       onFilterQueue={(prio, age) => setQuery({ view: null, state: "open", sev: PRIO_SEV[prio], age }, false)} />
      ) : (
        <main className="mx-auto grid min-h-0 w-full max-w-[1436px] items-start gap-5 px-4 pb-10 sm:px-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
          <section aria-label="Case queue" className="workspace-panel flex min-h-0 min-w-0 flex-col">
            <Summary an={an} queue={queue} />
            <Filters p={p} />
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto rounded-b-xl lg:max-h-[calc(100vh-300px)]"
                 onScroll={(e) => sessionStorage.setItem("trinetra.soc.scroll", String(e.currentTarget.scrollTop))}>
              {qState !== "ok" && <div className="p-3"><DataState state={qState} onRetry={loadQueue}
                emptyText={p.state === "needs_action" ? "Nothing needs action in this range." : "No cases match these filters."} /></div>}
              {queue && queue.items.length > 0 && <QueueTable q={queue} sort={p.sort} selected={selected} onOpen={openCase} />}
            </div>
          </section>
          <section aria-label="Selected case" className="workspace-panel hidden min-h-40 min-w-0 overflow-auto p-5 lg:block lg:max-h-[calc(100vh-210px)]">{casePane}</section>
        </main>
      )}
    </div>
  );
}

function useWide() {
  const [w, setW] = useState(() => matchMedia("(min-width: 1024px)").matches);
  useEffect(() => {
    const m = matchMedia("(min-width: 1024px)");
    const on = () => setW(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return w;
}

function Summary({ an, queue }: { an: Analytics | null; queue: Queue | null }) {
  const items: [string, string, string?][] = an ? [
    ["Open cases", String(an.queue.open_total)],
    ["Matching filters", queue ? String(queue.total) : "—"],
    ["Payments in range", String(an.volume.totals.total)],
    ["Intervention rate", rate(an.volume.intervention_rate), "Step-up, hold or block as a share of payments"],
    ["Worker backlog", String(an.worker.queued + an.worker.leased), an.worker.oldest_pending_age_ms ? `Oldest ${formatDuration(an.worker.oldest_pending_age_ms)}` : undefined],
  ] : [];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-t-xl border-b border-soc-line bg-primary-soft/65 px-4 py-4 sm:grid-cols-3 xl:grid-cols-5">
      {an ? items.map(([k, v, t]) => (
        <div key={k} title={t}><dt className="text-xs text-soc-muted">{k}</dt><dd className="num text-lg font-semibold">{v}</dd></div>
      )) : <div className="col-span-full h-11" aria-hidden />}
    </dl>
  );
}

function Filters({ p }: { p: ReturnType<typeof useQueryParams> }) {
  const states = [["needs_action", "Needs action"], ["open", "Open"], ["monitoring", "Monitoring"], ["closed", "Closed"], ["all", "All"]];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-soc-line px-4 py-2 text-xs">
      <div role="group" aria-label="Case state" className="flex flex-wrap gap-1">
        {states.map(([k, l]) => (
          <button key={k} aria-pressed={p.state === k} onClick={() => setQuery({ state: k, age: null })}
                  className={`min-h-10 rounded-lg px-2.5 font-semibold ${p.state === k ? "bg-primary-soft text-primary" : "text-soc-muted hover:bg-canvas hover:text-soc-ink"}`}>{l}</button>
        ))}
      </div>
      <label className="flex items-center gap-1.5 text-soc-muted">Severity
        <select className="rounded border border-soc-line bg-soc-canvas px-1.5 py-0.5 text-soc-ink" value={p.sev} onChange={(e) => setQuery({ sev: e.target.value })}>
          <option value="">Any</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
        </select></label>
      {p.age && <button className="rounded border border-soc-amber/50 px-2 py-0.5 text-soc-amber" onClick={() => setQuery({ age: null })}>
        Age {p.age.replace("lt_", "< ").replace("gt_", "> ").replace("_", "–")} · clear</button>}
    </div>
  );
}

const COLS: { key: string; label: string; sort?: string; right?: boolean }[] = [
  { key: "id", label: "Case" }, { key: "age", label: "Age", sort: "age" }, { key: "state", label: "Payment" },
  { key: "ben", label: "Beneficiary" }, { key: "amt", label: "Amount", sort: "amount", right: true },
  { key: "sev", label: "Severity", sort: "severity" }, { key: "upd", label: "Last update", sort: "updated" },
];

function QueueTable({ q, sort, selected, onOpen }: { q: Queue; sort: string; selected: string | null; onOpen: (id: string) => void }) {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Cases, sorted by {sort}. {q.total} total.</caption>
      <thead className="sticky top-0 z-10 bg-soc-canvas">
        <tr className="border-b border-soc-line">
          {COLS.map((c) => (
            <Th key={c.key} right={c.right} className="whitespace-nowrap" sort={c.sort ? (sort === c.sort ? (c.sort === "age" ? "ascending" : "descending") : "none") : undefined}>
              {c.sort ? (
                <button className="inline-flex items-center gap-1 hover:text-soc-ink"
                        onClick={() => setQuery({ sort: sort === c.sort ? "priority" : c.sort! })}>
                  {c.label}{sort === c.sort ? (c.sort === "age" ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />) : null}
                </button>
              ) : c.label}
            </Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {q.items.map((it) => (
          <tr key={it.case_id} aria-current={selected === it.case_id ? "true" : undefined}
              className={`cursor-pointer border-b border-soc-line/60 transition-colors ${selected === it.case_id ? "bg-soc-raised" : "hover:bg-soc-panel"}`}
              onClick={() => onOpen(it.case_id)}>
            <td className="px-2 py-2">
              <button className="font-mono text-xs text-soc-ink underline-offset-2 hover:underline" onClick={(e) => { e.stopPropagation(); onOpen(it.case_id); }}>
                {it.case_id.slice(-10)}
              </button>
              {it.pending_proposals > 0 && <span className="ml-2 rounded bg-soc-amber/15 px-1.5 py-0.5 text-[11px] text-soc-amber">{it.pending_proposals} to review</span>}
            </td>
            <td className="num whitespace-nowrap px-2 py-2 text-soc-muted">{formatDuration(it.age_ms)}</td>
            <td className="px-2 py-2"><PayState state={it.payment_state} /><span className="sr-only">, gateway {DECISION_LABEL[it.decision]}</span></td>
            <td className="px-2 py-2 text-soc-muted">{it.beneficiary_masked}</td>
            <td className="num whitespace-nowrap px-2 py-2 text-right">{it.amount_display}</td>
            <td className="px-2 py-2"><Severity sev={it.severity} /></td>
            <td className="num whitespace-nowrap px-2 py-2 text-soc-muted">{formatDateTime(it.updated_ms, TZ)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AnalyticsView({ an, state, bounds, onRetry, onFilterQueue }: {
  an: Analytics | null; state: QueryState; bounds: { from: number; to: number }; onRetry: () => void;
  onFilterQueue: (prio: string, age: string) => void;
}) {
  const [sel, setSel] = useState<{ start_ms: number; end_ms: number; decision?: string } | null>(null);
  const [rows, setRows] = useState<BucketRows | null>(null);
  const [rowsState, setRowsState] = useState<QueryState>("ok");
  const [models, setModels] = useState<ModelInfo | null>(null);
  useEffect(() => { soc.models().then(setModels).catch(() => undefined); }, []);
  useEffect(() => { setSel(null); setRows(null); }, [bounds]);
  useEffect(() => {
    if (!sel) return;
    setRowsState("loading");
    soc.rows(sel.start_ms, sel.end_ms, sel.decision).then((r) => { setRows(r); setRowsState(r.items.length ? "ok" : "empty"); })
      .catch(() => setRowsState("failed"));
  }, [sel]);

  if (!an) return <main className="p-4"><DataState state={state} onRetry={onRetry} /></main>;
  return (
    <main className="mx-auto w-full max-w-[1436px] space-y-4 px-4 pb-10 sm:px-10">
      <p className="text-xs text-soc-muted num">
        {formatDateTime(an.from_ms, TZ)} to {formatDateTime(an.to_ms, TZ)} · data as of cursor #{an.watermark.cursor}
        {state === "stale" && <span className="ml-2 text-soc-amber">Refresh failed; showing last result.</span>}
      </p>
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <div className="min-w-0 space-y-3">
          <VolumeChart a={an} tz={TZ} selected={sel} onSelect={setSel} />
          {sel && (
            <div className="workspace-panel overflow-auto p-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">{sel.decision ? DECISION_LABEL[sel.decision] : "All"} payments from {formatDateTime(sel.start_ms, TZ)}</h3>
                <button className="soc-btn-ghost px-2 py-1 text-xs" onClick={() => setSel(null)}>Clear</button>
              </div>
              {rowsState !== "ok" ? <DataState state={rowsState} /> : rows && (
                <table className="w-full text-sm">
                  <thead><tr><Th>Payment</Th><Th>Decision</Th><Th>Current state</Th><Th right>Amount</Th><Th>Case</Th></tr></thead>
                  <tbody>{rows.items.map((r) => (
                    <tr key={r.id} className="border-t border-soc-line/60">
                      <td className="px-2 py-1 font-mono text-xs">{r.id}</td><td className="px-2 py-1">{DECISION_LABEL[r.decision]}</td>
                      <td className="px-2 py-1"><PayState state={r.state} /></td><td className="num px-2 py-1 text-right">{r.amount_display}</td>
                      <td className="px-2 py-1">{r.case_id ? <button className="font-mono text-xs underline-offset-2 hover:underline"
                        onClick={() => setQuery({ view: null, case: r.case_id, state: "all" }, false)}>{r.case_id.slice(-10)}</button> : <span className="text-soc-faint">none</span>}</td>
                    </tr>))}</tbody>
                </table>
              )}
            </div>
          )}
        </div>
        <div className="min-w-0 space-y-4">
          <QueueAgeChart a={an} onSelect={onFilterQueue} />
          <ReviewTime a={an} />
        </div>
      </div>
      <QualityAndWorker a={an} />
      {models && (
        <div className="workspace-panel overflow-auto p-4">
          <h3 className="text-sm font-semibold">Local models and policy</h3>
          <p className="mt-0.5 text-xs text-soc-muted">Policy {models.policy_version}. Review-only signals never cause automatic holds.</p>
          <table className="mt-3 w-full text-sm">
            <thead><tr><Th>Signal</Th><Th>Checkpoint</Th><Th>Revision</Th><Th>Status</Th><Th>Use</Th></tr></thead>
            <tbody>{models.models.map((m) => (
              <tr key={m.key} className="border-t border-soc-line/60">
                <td className="px-2 py-1">{m.signal.replace(/_/g, " ")}</td>
                <td className="px-2 py-1 font-mono text-xs">{m.model_id}</td>
                <td className="max-w-[8rem] truncate px-2 py-1 font-mono text-xs text-soc-muted">{m.revision}</td>
                <td className={`px-2 py-1 ${m.status === "available" ? "" : "text-soc-muted"}`}>{m.status}<span className="block text-xs text-soc-faint">{m.reason}</span></td>
                <td className="px-2 py-1 text-xs">{m.enforce ? "Enforced" : "Review-only"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </main>
  );
}
