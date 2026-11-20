import { test } from "node:test";
import assert from "node:assert/strict";
import { formatINR, groupWhileTyping, parseINR, maskRef, formatDuration } from "./format.ts";

test("formatINR uses Indian grouping", () => {
  assert.equal(formatINR(1), "₹0.01");
  assert.equal(formatINR(100_000_00), "₹1,00,000.00");
  assert.equal(formatINR(1_234_567_89), "₹12,34,567.89");
  assert.equal(formatINR(25_000_00, { paise: false }), "₹25,000");
});

test("parseINR returns integer paise", () => {
  assert.deepEqual(parseINR("1,25,000.5"), { ok: true, minor: 12_500_050 });
  assert.deepEqual(parseINR("₹ 999"), { ok: true, minor: 99_900 });
  assert.equal(parseINR("0").ok, false);
  assert.equal(parseINR("12.345").ok, false);
  assert.equal(parseINR("-5").ok, false);
  assert.equal(parseINR("abc").ok, false);
  assert.equal(parseINR("").ok, false);
  assert.equal(parseINR("99999999999").ok, false);
});

test("groupWhileTyping", () => {
  assert.equal(groupWhileTyping("125000"), "1,25,000");
  assert.equal(groupWhileTyping("1250.5"), "1,250.5");
  assert.equal(groupWhileTyping("1250."), "1,250.");
  assert.equal(groupWhileTyping("00012"), "12");
});

test("maskRef and durations", () => {
  assert.equal(maskRef("HDFC00012345"), "•••• 2345");
  assert.equal(formatDuration(59_000), "59s");
  assert.equal(formatDuration(3_660_000), "1h 1m");
  assert.equal(formatDuration(null), "—");
});
