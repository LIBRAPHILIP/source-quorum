# SourceQuorum state design

Claims are stored in `TreeMap[str, str]` as canonical JSON. Variable-length
source lists and report lists do not fit cleanly in nested GenVM
collections; the schema below is the contract.

## Claim record

| Field | Type | Meaning |
|-------|------|---------|
| `claim_id` | string | Sequential id, `"0"`, `"1"`, … |
| `creator` | address hex | Only creator may add sources / lock |
| `question` | string | 16–2000 chars, the fact being settled |
| `claim_type` | `BINARY` \| `ENUM` \| `NUMERIC` | Extraction + quorum mode |
| `allowed_outcomes` | string[] | Fixed for BINARY; required for ENUM |
| `min_quorum` | int ≥ 2 | Votes needed for the winning label / band |
| `min_coverage` | int ≥ min_quorum | Successful fetches required |
| `tolerance_bps` | int | Numeric band (0 for non-numeric) |
| `challenge_budget` | int 0–3 | How many extra sources may be added |
| `challenge_window_secs` | int | 86400 when budget > 0, else 0. Not skippable. |
| `settled_at` | unix secs | Last resolve time (tx datetime) |
| `challenge_open_until` | unix secs | Finalize blocked while `now < this` |
| `challenges_used` | int | Consumed budget |
| `status` | see machine | Lifecycle |
| `sources` | `{url,label}[]` | Locked after `lock_sources` |
| `reports` | extract[] | Last consensus-accepted extracts |
| `outcome` | string | Winning label or `UNRESOLVED` |
| `numeric_value` | string \| null | Canonical decimal of `numeric_ticks` (`"100.0000"`) |
| `numeric_ticks` | int \| null | Payout bucket: `round(median * 10000)`. Compared exactly in consensus. |
| `tally` | object | Vote counts or band stats |
| `coverage` / `usable` | int | Fetch vs usable-extract counts |
| `reason` | string | Why it settled or failed |
| `quorum_met` | bool | Consumer flag |
| `resolve_count` | int | How many times consensus ran |

## State machine

```
                create_claim
                     │
                     ▼
                  DRAFT ──── add_source (creator, unique HTTPS URL)
                     │
                     │ lock_sources
                     ▼
                  LOCKED ──┐
                     │     │
                     │     │  resolve()  ← anyone
                     ▼     │
              ┌── SETTLED ─┴── UNRESOLVED
              │     │              │
              │     │ challenge() while window open
              │     └──────┬───────┘
              │            ▼
              │       CHALLENGED ── resolve() ──► SETTLED / UNRESOLVED
              │                   (SETTLED restarts the 24h window)
              │
              │ finalize() only after window closes
              ▼
            FINAL     (QuorumBond may assign a payee only now)
```

Illegal transitions raise (`sources_not_editable`, `not_resolvable`,
`only_settled_can_finalize`, `challenge_budget_exhausted`, …).

## Why this shape

- **Draft / lock** stops a resolver from racing a moving source set.
- **Challenge as an extra source** is the smallest honest appeal: the
  next resolve must re-fetch the whole set, including the new URL.
- **Finalize** cannot run during the challenge window. QuorumBond
  settles only from `FINAL`, so a later challenge cannot flip a payee.
- **UNRESOLVED is stored**, not thrown. Builders can wait, challenge,
  or give up without the last transaction reverting after expensive
  consensus.

## QuorumBond records

| Field | Meaning |
|-------|---------|
| `claim_id` | SourceQuorum claim this bond watches |
| `funder` / `beneficiary` | Parties |
| `expected_outcome` | Label that pays the beneficiary |
| `expected_numeric_min/max` | Optional band for `VALUE` claims |
| `amount` | GEN locked at `create_bond` (wei) |
| `status` | `OPEN` → `PAYABLE` → `PAID` \| `REFUNDED` |
| `payee` | Assigned at settle time |
| `withdrawn` | Idempotency flag |

`settle_bond` is idempotent. `withdraw` pays exactly once via
`emit_transfer(..., on='finalized')` so an appealed parent cannot
double-pay.
