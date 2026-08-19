# How SourceQuorum uses GenLayer consensus

Reviewers should treat this file as the specification. The Python in
`contracts/source_quorum.py` is the implementation.

## What is *not* happening

The leader's LLM does not decide the claim. A validator does not "check
that the JSON looks valid." There is no off-chain judge API.

A format-only validator (allowed enum, confidence 0–100, non-empty
summary) would be leader-output-only validation. GenLayer's own docs
reject that pattern. SourceQuorum does not use it.

## Two layers

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Non-deterministic extraction (inside run_nondet_unsafe)  │
│    Leader and each validator independently:                 │
│      for url in locked_sources:                             │
│          page = gl.nondet.web.get(url)                      │
│          fact = gl.nondet.exec_prompt(extract_one_source)   │
│    Compared fields: url set, fetch_ok, outcome, number      │
│    Ignored fields: excerpt, confidence, raw HTML            │
└─────────────────────────────────────────────────────────────┘
                              │ accepted extracts
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Deterministic settlement (outside the nondet block)      │
│    compute_quorum(claim_type, min_quorum, min_coverage,     │
│                   tolerance_bps, reports)                   │
│    Coverage gate → tally / median band → tie rejection      │
└─────────────────────────────────────────────────────────────┘
```

Storage writes happen only after consensus returns. That is required:
nondet blocks cannot write storage, call other contracts, or emit
messages.

## Leader

`leader_fn` closes over the locked URL list and the claim type. For
every URL it:

1. Fetches the page with `gl.nondet.web.get`.
2. Asks the LLM to extract a structured fact *from that page only*.
3. Normalizes the outcome (`YES`/`NO`, allowed enum, or `VALUE`).

If every fetch fails it raises `[TRANSIENT] all_sources_failed` so
validators can agree on a retry instead of settling an empty set.

## Validator

`validator_fn` receives `gl.vm.Result`.

| Leader result        | Validator action                                      |
|----------------------|-------------------------------------------------------|
| not `gl.vm.Return`   | Re-run `leader_fn` and classify the error             |
| malformed report list| Reject                                                |
| otherwise            | Re-run the full extract and compare decision fields   |

Comparison rules:

- URL identity and order must match the locked source set. The leader
  cannot invent, drop, or reorder sources.
- `fetch_ok` must match per URL. A leader success + validator failure
  is a reject (retry), not a settle.
- `outcome` must match after normalization.
- **Gate:** `UNRESOLVED` versus a concrete outcome is never equivalent.
  One node cannot "nudge" an unanswered source into a vote.
- Numeric values must lie within `tolerance_bps` of each other
  (time drift / extraction jitter). A 0-center only matches 0.

Excerpt and confidence are stored for humans. They are not consensus
inputs.

## Error classification

Mirrored from the official `run_nondet_unsafe` guidance:

- `[EXPECTED]` — deterministic application error; messages must match.
- `[TRANSIENT]` — both sides transient ⇒ agree, so the tx can retry
  cleanly rather than fork on timeouts.
- Anything else, including LLM parse chaos ⇒ disagree.

## Settlement math

Implemented twice on purpose:

- `contracts/source_quorum.py` — the on-chain copy (GenVM is
  self-contained).
- `lib/quorum_math.py` — the reviewable, unit-tested copy.

| Claim type | Settle when |
|------------|-------------|
| `BINARY`   | At least `min_quorum` independent `YES` or `NO` votes, and the winner strictly beats second place. |
| `ENUM`     | Same rule over the allow-list. Disallowed labels are ignored. |
| `NUMERIC`  | At least `min_quorum` extracted numbers, and at least `min_quorum` of them lie inside `tolerance_bps` of the median. Settled value is the median of that band. |

Ties, coverage failures, and numeric dispersion all return
`UNRESOLVED`. That is a first-class status, not a crash.

## Challenge / finalize

This is the primitive's appeal path, distinct from protocol-level
validator appeals:

1. `resolve` may be called in `LOCKED`, `UNRESOLVED`, or `CHALLENGED`.
2. Anyone may `challenge` a `SETTLED` or `UNRESOLVED` claim by adding
   one new HTTPS source, while `challenges_used < challenge_budget`.
3. A challenged claim must be resolved again against the expanded set.
4. `finalize` freezes a `SETTLED` claim. `get_settlement` then becomes
   the immutable consumer API.

Protocol-level appeals still apply to every write: if validators
disagree, the leader rotates; if consensus cannot form, the transaction
is undetermined and state does not change.

## What composing contracts should read

`get_settlement(claim_id)` is the only surface `QuorumBond` uses. It
never re-runs an LLM. Cross-contract reads go through
`gl.get_contract_at` / `@gl.contract_interface` in the deterministic
context, as required by GenVM.
