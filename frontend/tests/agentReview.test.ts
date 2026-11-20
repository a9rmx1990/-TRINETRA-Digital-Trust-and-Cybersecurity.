import assert from 'node:assert/strict';
import { test } from 'node:test';
import { proposalControls } from '../src/agentReview.ts';

test('active proposals allow rejection and respect the configured approval tier', () => {
  const proposal = { status: 'pending', action: 'freeze', case_version: 3 };
  assert.deepEqual(proposalControls(proposal, 3, { kill_switch: false, max_tier: 1 }), {
    status: 'pending', reviewable: true, approvable: false,
  });
  assert.equal(proposalControls(proposal, 3, { kill_switch: false, max_tier: 2 }).approvable, true);
  assert.equal(proposalControls(proposal, 3, { kill_switch: true, max_tier: 2 }).approvable, false);
});

test('a case update marks an unresolved proposal stale', () => {
  const proposal = { status: 'queued', action: 'step_up', case_version: 3 };
  assert.deepEqual(proposalControls(proposal, 4, { kill_switch: false, max_tier: 1 }), {
    status: 'stale', reviewable: false, approvable: false,
  });
  assert.equal(proposalControls({ ...proposal, status: 'applied' }, 4, {
    kill_switch: false, max_tier: 1,
  }).status, 'applied');
});
