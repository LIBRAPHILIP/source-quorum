/**
 * Node port of the settlement tests so CI can run without Python.
 * Keep in lockstep with lib/quorum_math.py and tests/test_quorum_math.py.
 */
import test from "node:test";
import assert from "node:assert/strict";

const UNRESOLVED = "UNRESOLVED";
const SETTLED = "SETTLED";
const BINARY_OUTCOMES = new Set(["YES", "NO"]);

function normalizeOutcome(raw, claimType, allowed) {
  if (raw == null) return UNRESOLVED;
  let text = String(raw).trim().toUpperCase();
  const aliases = {
    TRUE: "YES",
    Y: "YES",
    SUPPORT: "YES",
    SUPPORTED: "YES",
    FALSE: "NO",
    N: "NO",
    REJECT: "NO",
    REJECTED: "NO",
    CONTESTED: "NO",
    UNKNOWN: UNRESOLVED,
    UNDETERMINED: UNRESOLVED,
    INSUFFICIENT: UNRESOLVED,
    INSUFFICIENT_EVIDENCE: UNRESOLVED,
    NONE: UNRESOLVED,
    "": UNRESOLVED,
  };
  text = aliases[text] ?? text;
  if (claimType === "BINARY") return BINARY_OUTCOMES.has(text) ? text : UNRESOLVED;
  if (claimType === "ENUM") {
    const allow = allowed.map((a) => String(a).trim().toUpperCase());
    return allow.includes(text) ? text : UNRESOLVED;
  }
  if (claimType === "NUMERIC") return text === UNRESOLVED || text === "" ? UNRESOLVED : "VALUE";
  return UNRESOLVED;
}

function parseNumber(raw) {
  if (raw == null || raw === "") return null;
  if (typeof raw === "boolean") return null;
  if (typeof raw === "number") return raw;
  const text = String(raw).trim().replace(/,/g, "").replace(/%$/, "");
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function median(values) {
  const ordered = [...values].sort((a, b) => a - b);
  const n = ordered.length;
  const mid = Math.floor(n / 2);
  if (n % 2 === 1) return ordered[mid];
  return (ordered[mid - 1] + ordered[mid]) / 2;
}

function withinTolerance(value, center, bps) {
  if (bps < 0) return false;
  if (center === 0) return value === 0;
  return Math.abs(value - center) / Math.abs(center) <= bps / 10000;
}

const NUMERIC_SCALE = 10000;

function canonicalizeNumeric(value) {
  const n = parseNumber(value);
  if (n == null) return null;
  const scaled = n * NUMERIC_SCALE;
  return scaled >= 0 ? Math.trunc(scaled + 0.5) : Math.trunc(scaled - 0.5);
}

function ticksToDisplay(ticks) {
  if (ticks == null) return null;
  const sign = ticks < 0 ? "-" : "";
  const t = Math.abs(ticks);
  const whole = Math.floor(t / NUMERIC_SCALE);
  const frac = t % NUMERIC_SCALE;
  return `${sign}${whole}.${String(frac).padStart(4, "0")}`;
}

function fail(reason, tally, coverage) {
  return {
    status: UNRESOLVED,
    outcome: UNRESOLVED,
    numeric_value: null,
    numeric_ticks: null,
    reason,
    coverage,
    quorum_met: false,
    tally,
  };
}

function computeQuorum(claimType, allowed, minQuorum, minCoverage, toleranceBps, reports) {
  const fetched = reports.filter((r) => r.fetch_ok);
  const coverage = fetched.length;
  if (coverage < minCoverage) return fail("insufficient_coverage", {}, coverage);
  if (claimType === "NUMERIC") {
    const values = [];
    for (const r of fetched) {
      if (normalizeOutcome(r.outcome, "NUMERIC", []) === UNRESOLVED) continue;
      const n = parseNumber(r.numeric_value);
      if (n != null) values.push(n);
    }
    const tally = { VALUE: values.length, UNRESOLVED: coverage - values.length };
    if (values.length < minQuorum) return fail("no_quorum", tally, coverage);
    const center = median(values);
    const band = values.filter((v) => withinTolerance(v, center, toleranceBps));
    if (band.length < minQuorum) return fail("numeric_dispersion", tally, coverage);
    const ticks = canonicalizeNumeric(median(band));
    return {
      status: SETTLED,
      outcome: "VALUE",
      numeric_value: ticksToDisplay(ticks),
      numeric_ticks: ticks,
      reason: "numeric_band",
      coverage,
      quorum_met: true,
      tally: { in_band: band.length, extracted: values.length },
    };
  }
  const tally = {};
  let usable = 0;
  for (const r of fetched) {
    const o = normalizeOutcome(r.outcome, claimType, allowed);
    if (o === UNRESOLVED) continue;
    tally[o] = (tally[o] || 0) + 1;
    usable += 1;
  }
  if (usable < minQuorum || !Object.keys(tally).length) return fail("no_quorum", tally, coverage);
  const ranked = Object.entries(tally).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const [winner, winCount] = ranked[0];
  const second = ranked[1]?.[1] ?? 0;
  if (winCount < minQuorum) return fail("no_quorum", tally, coverage);
  if (winCount === second) return fail("tie", tally, coverage);
  return {
    status: SETTLED,
    outcome: winner,
    numeric_value: null,
    numeric_ticks: null,
    reason: "quorum",
    coverage,
    quorum_met: true,
    tally,
  };
}

function reportsEquivalent(leader, validator, claimType, bps) {
  if (!Array.isArray(leader) || !Array.isArray(validator) || leader.length !== validator.length) {
    return false;
  }
  const left = {};
  const right = {};
  for (const row of leader) {
    if (!row.url || left[row.url]) return false;
    left[row.url] = row;
  }
  for (const row of validator) {
    if (!row.url || right[row.url]) return false;
    right[row.url] = row;
  }
  if (Object.keys(left).sort().join() !== Object.keys(right).sort().join()) return false;
  for (const url of Object.keys(left)) {
    const L = left[url];
    const V = right[url];
    if (Boolean(L.fetch_ok) !== Boolean(V.fetch_ok)) return false;
    if (!L.fetch_ok) continue;
    const lo = normalizeOutcome(L.outcome, claimType, []);
    const vo = normalizeOutcome(V.outcome, claimType, []);
    if (lo === UNRESOLVED || vo === UNRESOLVED) {
      if (lo !== vo) return false;
      continue;
    }
    if (lo !== vo) return false;
    if (claimType === "NUMERIC") {
      const ln = parseNumber(L.numeric_value);
      const vn = parseNumber(V.numeric_value);
      if (ln == null || vn == null) return false;
      if (!withinTolerance(ln, vn, bps) && !withinTolerance(vn, ln, bps)) return false;
    }
  }
  return true;
}

const r = (url, ok, outcome, n) => ({
  url,
  fetch_ok: ok,
  outcome,
  numeric_value: n ?? null,
  excerpt: "ignored",
  confidence: 80,
});

test("binary quorum of three YES settles", () => {
  const result = computeQuorum(
    "BINARY",
    ["YES", "NO"],
    2,
    2,
    0,
    [r("https://a.example/1", true, "YES"), r("https://b.example/1", true, "YES"), r("https://c.example/1", true, "YES")]
  );
  assert.equal(result.status, "SETTLED");
  assert.equal(result.outcome, "YES");
});

test("binary tie is unresolved", () => {
  const result = computeQuorum(
    "BINARY",
    ["YES", "NO"],
    2,
    2,
    0,
    [
      r("https://a.example/1", true, "YES"),
      r("https://b.example/1", true, "YES"),
      r("https://c.example/1", true, "NO"),
      r("https://d.example/1", true, "NO"),
    ]
  );
  assert.equal(result.reason, "tie");
});

test("coverage gate", () => {
  const result = computeQuorum(
    "BINARY",
    ["YES", "NO"],
    2,
    2,
    0,
    [r("https://a.example/1", true, "YES"), r("https://b.example/1", false, "UNRESOLVED")]
  );
  assert.equal(result.reason, "insufficient_coverage");
});

test("enum majority", () => {
  const result = computeQuorum(
    "ENUM",
    ["HOME", "AWAY", "DRAW"],
    2,
    2,
    0,
    [r("https://a.example/1", true, "HOME"), r("https://b.example/1", true, "HOME"), r("https://c.example/1", true, "AWAY")]
  );
  assert.equal(result.outcome, "HOME");
});

test("numeric median band", () => {
  const result = computeQuorum(
    "NUMERIC",
    [],
    2,
    2,
    200,
    [r("https://a.example/1", true, "VALUE", 100), r("https://b.example/1", true, "VALUE", 101), r("https://c.example/1", true, "VALUE", 99.5)]
  );
  assert.equal(result.status, "SETTLED");
  assert.equal(result.numeric_ticks, canonicalizeNumeric(100));
  assert.equal(result.numeric_value, "100.0000");
});

test("straddling medians are different payout buckets", () => {
  const low = canonicalizeNumeric(99.99);
  const high = canonicalizeNumeric(100.01);
  assert.notEqual(low, high);
});

test("numeric dispersion", () => {
  const result = computeQuorum(
    "NUMERIC",
    [],
    2,
    2,
    100,
    [r("https://a.example/1", true, "VALUE", 10), r("https://b.example/1", true, "VALUE", 50), r("https://c.example/1", true, "VALUE", 90)]
  );
  assert.equal(result.reason, "numeric_dispersion");
});

test("equivalence ignores excerpt and aliases YES", () => {
  assert.equal(
    reportsEquivalent(
      [r("https://a.example/1", true, "YES")],
      [{ url: "https://a.example/1", fetch_ok: true, outcome: "true", excerpt: "other", confidence: 10 }],
      "BINARY",
      0
    ),
    true
  );
});

test("unresolved gate rejects", () => {
  assert.equal(
    reportsEquivalent([r("https://a.example/1", true, "YES")], [r("https://a.example/1", true, "UNRESOLVED")], "BINARY", 0),
    false
  );
});

test("leader cannot swap urls", () => {
  assert.equal(
    reportsEquivalent([r("https://a.example/1", true, "YES")], [r("https://evil.example/1", true, "YES")], "BINARY", 0),
    false
  );
});
