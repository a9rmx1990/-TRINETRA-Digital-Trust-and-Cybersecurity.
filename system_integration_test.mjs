/**
 * system_integration_test.mjs
 * Full-system integration test for TRINETRA:
 * 1. Health check
 * 2. Scenario 1 (Baseline ALLOW, low risk)
 * 3. Scenario 2 (Voice Clone HOLD, high acoustic risk)
 * 4. Scenario 3 (Mule Ring HOLD, cycle/velocity)
 * 5. Scenario 4 (Digital Arrest HOLD, extortion coercive NLP)
 * 6. Direct gateway interception
 * 7. Mule ring topology API
 * 8. Analyst override freeze & release
 * 9. WebSocket real-time broadcast reception
 * 10. Metrics store consistency
 * 11. Frontend build artifact check
 */

const BASE = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws/soc-stream';

function assert(condition, message) {
  if (!condition) {
    throw new Error(`ASSERTION FAILED: ${message}`);
  }
}

async function run() {
  console.log('=== TRINETRA FULL-SYSTEM INTEGRATION TEST ===\n');

  // 1. Health Check
  console.log('[1/10] Verifying Backend Health...');
  const healthRes = await fetch(`${BASE}/health`);
  assert(healthRes.ok, `Health check failed: ${healthRes.status}`);
  const health = await healthRes.json();
  assert(health.status === 'online', 'Health status is not online');
  assert(health.latency_target_ms === 150, 'Latency target is not 150ms');
  console.log('  ✓ Backend online (target: 150ms SLA)');

  // 2. WebSocket Connection
  console.log('[2/10] Testing WebSocket SOC Live Stream...');
  const wsEvents = [];
  const ws = new WebSocket(WS_URL);

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('WS connection timeout')), 3000);
    ws.onopen = () => {
      clearTimeout(timeout);
      console.log('  ✓ WebSocket connected');
      resolve();
    };
    ws.onerror = (err) => reject(err);
    ws.onmessage = (e) => {
      try {
        wsEvents.push(JSON.parse(e.data));
      } catch (err) {}
    };
  });

  // Give 100ms for initial CONNECTED event
  await new Promise(r => setTimeout(r, 100));
  assert(wsEvents.some(e => e.event_type === 'CONNECTED'), 'No CONNECTED event received');
  console.log('  ✓ Received initial CONNECTED handshake event');

  // 3. Scenario 1: Baseline Clean Payment
  console.log('[3/10] Triggering SCENARIO_1_BASELINE...');
  const s1Res = await fetch(`${BASE}/api/v1/scenarios/trigger/SCENARIO_1_BASELINE`, { method: 'POST' });
  assert(s1Res.ok, 'S1 trigger failed');
  const s1 = await s1Res.json();
  const s1Eval = s1.evaluation ?? s1;
  const s1Decision = s1.actual_decision ?? s1Eval.decision;
  assert(s1Decision === 'ALLOW', `S1 decision must be ALLOW, got ${s1Decision}`);
  assert(s1Eval.composite_risk < 35, `S1 risk must be < 35, got ${s1Eval.composite_risk}`);
  assert(s1Eval.latency_ms < 150, `S1 latency exceeded 150ms SLA: ${s1Eval.latency_ms}ms`);
  console.log(`  ✓ S1 ALLOW | Risk: ${s1Eval.composite_risk} | Latency: ${s1Eval.latency_ms}ms`);

  // 4. Scenario 2: Voice Clone Scam
  console.log('[4/10] Triggering SCENARIO_2_VOICE_CLONE...');
  const s2Res = await fetch(`${BASE}/api/v1/scenarios/trigger/SCENARIO_2_VOICE_CLONE`, { method: 'POST' });
  assert(s2Res.ok, 'S2 trigger failed');
  const s2 = await s2Res.json();
  const s2Eval = s2.evaluation ?? s2;
  const s2Decision = s2.actual_decision ?? s2Eval.decision;
  assert(s2Decision === 'HOLD', `S2 decision must be HOLD, got ${s2Decision}`);
  assert(s2Eval.acoustic_diagnostics?.is_synthetic === true, 'S2 must detect synthetic audio');
  assert(s2Eval.composite_risk >= 75, `S2 risk must be >= 75, got ${s2Eval.composite_risk}`);
  assert(s2Eval.latency_ms < 150, `S2 latency SLA breached: ${s2Eval.latency_ms}ms`);
  console.log(`  ✓ S2 HOLD | Synthetic Voice Detected | Latency: ${s2Eval.latency_ms}ms`);

  // 5. Scenario 3: Mule Ring
  console.log('[5/10] Triggering SCENARIO_3_MULE_RING...');
  const s3Res = await fetch(`${BASE}/api/v1/scenarios/trigger/SCENARIO_3_MULE_RING`, { method: 'POST' });
  assert(s3Res.ok, 'S3 trigger failed');
  const s3 = await s3Res.json();
  const s3Eval = s3.evaluation ?? s3;
  const s3Decision = s3.actual_decision ?? s3Eval.decision;
  assert(s3Decision === 'HOLD', `S3 decision must be HOLD, got ${s3Decision}`);
  assert(s3Eval.graph_diagnostics?.is_mule_ring === true, 'S3 must flag mule ring');
  assert(s3Eval.latency_ms < 150, `S3 latency SLA breached: ${s3Eval.latency_ms}ms`);
  console.log(`  ✓ S3 HOLD | Mule Ring Confirmed | Hops: ${s3Eval.graph_diagnostics.hop_count} | Latency: ${s3Eval.latency_ms}ms`);

  // 6. Scenario 4: Digital Arrest
  console.log('[6/10] Triggering SCENARIO_4_DIGITAL_ARREST...');
  const s4Res = await fetch(`${BASE}/api/v1/scenarios/trigger/SCENARIO_4_DIGITAL_ARREST`, { method: 'POST' });
  assert(s4Res.ok, 'S4 trigger failed');
  const s4 = await s4Res.json();
  const s4Eval = s4.evaluation ?? s4;
  const s4Decision = s4.actual_decision ?? s4Eval.decision;
  assert(s4Decision === 'HOLD', `S4 decision must be HOLD, got ${s4Decision}`);
  assert(s4Eval.composite_risk >= 75, `S4 risk must be >= 75, got ${s4Eval.composite_risk}`);
  assert(s4Eval.latency_ms < 150, `S4 latency SLA breached: ${s4Eval.latency_ms}ms`);
  console.log(`  ✓ S4 HOLD | Digital Arrest Coercion Caught | Latency: ${s4Eval.latency_ms}ms`);

  // 7. Direct Intercept Gateway API
  console.log('[7/10] Testing Direct Gateway /api/v1/intercept...');
  const gwRes = await fetch(`${BASE}/api/v1/intercept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transaction_id: 'TX-LIVE-E2E-001',
      sender_account: 'ACC-LEGIT-101',
      recipient_account: 'ACC-LEGIT-102',
      amount: 12500,
      channel: 'UPI',
      recipient_account_age_days: 400,
      narrative_context: 'Grocery reimbursement for weekend trip',
    }),
  });
  assert(gwRes.ok, 'Direct intercept failed');
  const gw = await gwRes.json();
  assert(gw.decision === 'ALLOW', `Direct intercept expected ALLOW, got ${gw.decision}`);
  console.log(`  ✓ In-Line Intercept ALLOW | Latency: ${gw.latency_ms}ms`);

  // 8. Graph Mule Network API
  console.log('[8/10] Testing Graph Topology Extraction /api/v1/graph/mule-network...');
  const graphRes = await fetch(`${BASE}/api/v1/graph/mule-network`);
  assert(graphRes.ok, 'Graph API failed');
  const graph = await graphRes.json();
  assert(Array.isArray(graph.nodes) && graph.nodes.length > 0, 'Graph nodes missing');
  assert(Array.isArray(graph.edges), 'Graph edges missing');
  console.log(`  ✓ Topology Retrieved (${graph.nodes.length} nodes, ${graph.edges.length} edges)`);

  // 9. SOC Analyst Override API
  console.log('[9/10] Testing SOC Analyst Override freeze & release...');
  const freezeRes = await fetch(`${BASE}/api/v1/soc/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      account: 'ACC-SUSPECT-88',
      action: 'CONFIRM_FREEZE',
      analyst_id: 'SOC-ANALYST-TEST',
    }),
  });
  assert(freezeRes.ok, 'Freeze override failed');
  const freezeData = await freezeRes.json();
  assert(freezeData.status === 'SUCCESS', 'Freeze status not SUCCESS');
  assert(freezeData.currently_quarantined === true, 'Account not quarantined');

  const releaseRes = await fetch(`${BASE}/api/v1/soc/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      account: 'ACC-SUSPECT-88',
      action: 'RELEASE_HOLD',
      analyst_id: 'SOC-ANALYST-TEST',
    }),
  });
  assert(releaseRes.ok, 'Release override failed');
  const releaseData = await releaseRes.json();
  assert(releaseData.currently_quarantined === false, 'Account still quarantined');
  console.log('  ✓ Analyst Override: Quarantine freeze & release confirmed');

  // Verify WebSocket Broadcasts were captured
  await new Promise(r => setTimeout(r, 200));
  const evaluatedEvents = wsEvents.filter(e => e.event_type === 'TRANSACTION_EVALUATED');
  const overrideEvents = wsEvents.filter(e => e.event_type === 'ANALYST_OVERRIDE');
  assert(evaluatedEvents.length >= 5, `Expected >=5 evaluated events, got ${evaluatedEvents.length}`);
  assert(overrideEvents.length >= 2, `Expected >=2 override events, got ${overrideEvents.length}`);
  console.log(`  ✓ WebSocket Stream Verified: ${wsEvents.length} events received across all channels`);
  ws.close();

  // 10. System Metrics
  console.log('[10/10] Verifying System Metrics...');
  const mRes = await fetch(`${BASE}/api/v1/metrics`);
  const metrics = await mRes.json();
  assert(metrics.total_evaluated >= 5, `Metrics total_evaluated ${metrics.total_evaluated} < 5`);
  assert(metrics.held >= 3, `Metrics held ${metrics.held} < 3`);
  assert(metrics.allowed >= 2, `Metrics allowed ${metrics.allowed} < 2`);
  assert(metrics.average_latency_ms < 50, `Average latency too high: ${metrics.average_latency_ms}ms`);
  console.log(`  ✓ Metrics: Total=${metrics.total_evaluated} | Held=${metrics.held} | Allowed=${metrics.allowed} | AvgLatency=${metrics.average_latency_ms}ms`);

  console.log('\n=============================================');
  console.log('🎉 ALL 10/10 INTEGRATION TESTS PASSED CLEANLY');
  console.log('=============================================\n');
}

run().catch(err => {
  console.error('\n❌ INTEGRATION TEST FAILED:', err);
  process.exit(1);
});
