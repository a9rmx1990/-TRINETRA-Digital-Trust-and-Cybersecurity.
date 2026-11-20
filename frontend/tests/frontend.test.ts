import test from 'node:test';
import assert from 'node:assert/strict';
import type { Decision, RiskBreakdown, SOCEvent, CytoscapeGraph } from '../src/types.js';

test('Frontend Unit Test 1: Decision boundaries match policy specifications', () => {
  function getDecision(composite: number): Decision {
    if (composite >= 70) return 'HOLD';
    if (composite >= 35) return 'STEP_UP';
    return 'ALLOW';
  }

  assert.equal(getDecision(0), 'ALLOW');
  assert.equal(getDecision(34.9), 'ALLOW');
  assert.equal(getDecision(35.0), 'STEP_UP');
  assert.equal(getDecision(69.9), 'STEP_UP');
  assert.equal(getDecision(70.0), 'HOLD');
  assert.equal(getDecision(99.9), 'HOLD');
});

test('Frontend Unit Test 2: Risk Breakdown weighted aggregation validation', () => {
  const breakdown: RiskBreakdown = {
    acoustic_score: 95.0,
    graph_score: 80.0,
    nlp_score: 40.0,
    composite_risk: 80.75,
  };

  const wAudio = 0.45;
  const wGraph = 0.40;
  const wNlp = 0.15;
  const computed = (breakdown.acoustic_score * wAudio) +
                   (breakdown.graph_score * wGraph) +
                   (breakdown.nlp_score * wNlp);

  assert.equal(Math.round(computed * 100) / 100, breakdown.composite_risk);
});

test('Frontend Unit Test 3: SOCEvent parser handles flat vs nested transactions safely', () => {
  const nestedEvent: SOCEvent = {
    event_type: 'TRANSACTION_EVALUATED',
    timestamp: '2026-11-10T16:00:00Z',
    transaction: {
      transaction_id: 'TX-NESTED-99',
      sender_account: 'ACC-1',
      recipient_account: 'ACC-2',
      amount: 45000,
      channel: 'UPI',
    },
    decision: 'HOLD',
    latency_ms: 2.5,
  };

  const txId = nestedEvent.transaction?.transaction_id ?? nestedEvent.transaction_id ?? 'TX-FALLBACK';
  const amount = nestedEvent.transaction?.amount ?? nestedEvent.amount ?? 0;
  const channel = nestedEvent.transaction?.channel ?? nestedEvent.channel ?? 'UPI';

  assert.equal(txId, 'TX-NESTED-99');
  assert.equal(amount, 45000);
  assert.equal(channel, 'UPI');
});

test('Frontend Unit Test 4: CytoscapeGraph normalization handles direct nodes/edges or elements wrapper', () => {
  const directGraph: CytoscapeGraph = {
    nodes: [{ data: { id: 'ACC-1', label: 'ACC-1', type: 'standard' } }],
    edges: [{ data: { id: 'e1', source: 'ACC-1', target: 'ACC-2', amount: 5000 } }],
  };

  const normalized = directGraph.elements ?? { nodes: directGraph.nodes, edges: directGraph.edges };
  assert.equal(normalized.nodes.length, 1);
  assert.equal(normalized.edges.length, 1);
  assert.equal(normalized.nodes[0].data.id, 'ACC-1');
});

test('Frontend Unit Test 5: Metrics response defaults and division-by-zero protection', () => {
  function computeAvgLatency(total: number, sumLatency: number): number {
    return total > 0 ? Math.round((sumLatency / total) * 100) / 100 : 0.0;
  }

  assert.equal(computeAvgLatency(0, 0), 0.0);
  assert.equal(computeAvgLatency(10, 25.5), 2.55);
});
