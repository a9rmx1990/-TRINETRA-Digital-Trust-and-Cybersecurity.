export function proposalControls(
  proposal: { status: string; action: string; case_version: number },
  caseVersion: number,
  controls: { kill_switch: boolean; max_tier: number },
) {
  const pending = proposal.status === 'pending' || proposal.status === 'queued';
  const stale = pending && proposal.case_version !== caseVersion;
  const tier = ['freeze', 'block_beneficiary', 'report'].includes(proposal.action) ? 2 : 1;
  return {
    status: stale ? 'stale' : proposal.status,
    reviewable: pending && !stale,
    approvable: pending && !stale && !controls.kill_switch && controls.max_tier >= tier,
  };
}
