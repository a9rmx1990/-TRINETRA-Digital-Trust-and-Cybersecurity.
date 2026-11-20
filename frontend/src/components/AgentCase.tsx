import type { FormEvent } from 'react';
import type { Case } from '../sandbox';
import { proposalControls } from '../agentReview';

const actionLabels: Record<string, string> = {
  step_up: 'Issue step-up challenge',
  hold: 'Temporarily hold transfer',
  watchlist: 'Expedite watch',
  close_case: 'Close verified case as benign',
  freeze: 'Freeze account',
  block_beneficiary: 'Block beneficiary',
  report: 'Approve investigation report',
};

type Props = {
  item: Case;
  busy: boolean;
  review: (id: string, decision: 'approve' | 'reject', note: string) => void;
  override: (verdict: 'fraud' | 'suspicious' | 'benign', note: string) => void;
  toggle: (enabled: boolean) => void;
  revealChallenge: () => void;
};

function timestamp(seconds: number) {
  return new Date(seconds * 1000).toLocaleString();
}

export default function AgentCase({ item, busy, review, override, toggle, revealChallenge }: Props) {
  const agent = item.agent;
  if (!agent) return null;
  const verdict = item.triage.verdict;

  function submitReview(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    const button = (event.nativeEvent as SubmitEvent).submitter;
    const note = String(new FormData(event.currentTarget).get('note')).trim();
    review(id, button?.getAttribute('value') === 'approve' ? 'approve' : 'reject', note);
  }

  return (
    <section className="space-y-4 rounded-xl border border-white/10 p-4" aria-labelledby="agent-case-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id="agent-case-heading" className="text-sm font-semibold text-slate-100">SOC agent</h3>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-300">
            {agent.kill_switch || agent.max_tier === 0 ? 'Read-only mode' : 'Tier ' + agent.max_tier + ' enabled'}
          </span>
          {agent.max_tier > 0 && (
            <button type="button" className="secondary min-h-11" disabled={busy}
              onClick={() => toggle(!agent.kill_switch)}>
              {agent.kill_switch ? 'Resume agent actions' : 'Pause agent actions'}
            </button>
          )}
        </div>
      </div>

      {verdict && (
        <div className="space-y-1 text-sm text-slate-300">
          <p><strong className="capitalize text-slate-100">{verdict.verdict}</strong> · {Math.round(verdict.confidence * 100)}% confidence</p>
          <p>{verdict.rationale}</p>
          <p className="break-all text-slate-400">Evidence {verdict.evidence_ids.join(', ')}</p>
        </div>
      )}
      {agent.watch && (
        <p className="text-sm text-slate-300">
          {agent.watch.status === 'active'
            ? 'Next watch check ' + timestamp(agent.watch.next_at)
            : 'Watch completed ' + timestamp(agent.watch.through_at)}
        </p>
      )}
      {agent.hold_until != null && (
        <p role="status" className="text-sm text-amber-200">Temporary hold until {timestamp(agent.hold_until)}</p>
      )}

      {agent.proposals.map(proposal => {
        const controls = proposalControls(proposal, item.version, agent);
        return (
          <div key={proposal.id} className="space-y-2 border-t border-white/10 pt-3 text-sm text-slate-300">
            <p><strong className="text-slate-100">{actionLabels[proposal.action] ?? proposal.action}</strong> · {controls.status}</p>
            {proposal.note && <p className="break-words">{proposal.note}</p>}
            {controls.reviewable && (
              <form className="space-y-2" onSubmit={event => submitReview(event, proposal.id)}>
                <label className="block">
                  <span className="block pb-1">Review rationale</span>
                  <input name="note" className="w-full rounded border border-white/20 bg-slate-900 p-2 text-slate-100"
                    minLength={3} maxLength={500} required />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="submit" className="primary min-h-11" value="approve"
                    disabled={busy || !controls.approvable}>Approve</button>
                  <button type="submit" className="secondary min-h-11" value="reject" disabled={busy}>Reject</button>
                </div>
              </form>
            )}
          </div>
        );
      })}
      {item.state === 'STEP_UP_REQUIRED'
        && agent.proposals.some(proposal => proposal.action === 'step_up' && proposal.status === 'applied') && (
          <button type="button" className="secondary min-h-11" disabled={busy} onClick={revealChallenge}>
            Show active verification code
          </button>
      )}

      {verdict && (
        <form className="space-y-2 border-t border-white/10 pt-3 text-sm text-slate-300" onSubmit={event => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const label = data.get('verdict');
          if (label === 'fraud' || label === 'suspicious' || label === 'benign') {
            override(label, String(data.get('note')).trim());
          }
        }}>
          <label className="block">
            <span className="block pb-1">Analyst verdict</span>
            <select name="verdict" className="min-h-11 rounded border border-white/20 bg-slate-900 p-2"
              key={item.version + '-' + (agent.feedback?.verdict ?? verdict.verdict)}
              defaultValue={agent.feedback?.verdict ?? verdict.verdict}>
              <option value="fraud">Fraud</option>
              <option value="suspicious">Suspicious</option>
              <option value="benign">Benign</option>
            </select>
          </label>
          <label className="block">
            <span className="block pb-1">Override rationale</span>
            <input name="note" className="w-full rounded border border-white/20 bg-slate-900 p-2 text-slate-100"
              minLength={3} maxLength={500} required />
          </label>
          <button type="submit" className="secondary min-h-11" disabled={busy}>Save analyst verdict</button>
          {agent.feedback && <p role="status">Saved analyst verdict: {agent.feedback.verdict}</p>}
        </form>
      )}

      <details className="text-sm text-slate-300">
        <summary className="cursor-pointer py-2 font-medium text-slate-100">Agent timeline</summary>
        {agent.timeline.length ? (
          <ol className="max-h-52 space-y-1 overflow-y-auto">
            {agent.timeline.map(step => (
              <li key={step.seq} className="break-words">
                <time dateTime={new Date(step.created_at * 1000).toISOString()}>{timestamp(step.created_at)}</time>
                {' · '}{step.role} · {step.tool.replace(/_/g, ' ')} · {step.outcome}
              </li>
            ))}
          </ol>
        ) : <p>Investigation queued.</p>}
      </details>
    </section>
  );
}
