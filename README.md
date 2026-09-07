# SourceQuorum

**A reusable multi-source fact settlement primitive for [GenLayer](https://genlayer.com) Intelligent Contracts.**

The LLM does not decide the claim. Validators independently re-fetch every locked source, re-extract a structured fact from each page, and compare **decision fields**. Settlement (including the NUMERIC payout bucket) is computed **inside** consensus. Numeric results are integer ticks (`round(median * 10000)`), not a raw leader median, so QuorumBond cannot pay different people from two validator-compatible extracts.

This repository is a contract primitive, not a product app.

- GitHub: https://github.com/LIBRAPHILIP/source-quorum
- Docs: https://source-quorum.vercel.app

| | |
|---|---|
| Primitive | [`contracts/source_quorum.py`](contracts/source_quorum.py) |
| Consumer | [`contracts/quorum_bond.py`](contracts/quorum_bond.py) |
| Settlement math | [`lib/quorum_math.py`](lib/quorum_math.py) |
| Consensus spec | [`docs/CONSENSUS.md`](docs/CONSENSUS.md) |
| State machine | [`docs/STATE.md`](docs/STATE.md) |
| Docs site | https://source-quorum.vercel.app |
| Live v1.2.0 (Studionet) | [`0x4c9930DC11Cad44dA46CBB3Cd5D6C73BC2fba476`](https://explorer-studio.genlayer.com/address/0x4c9930DC11Cad44dA46CBB3Cd5D6C73BC2fba476) |

## Why this exists

GenLayer already shows single-URL examples (a football score page, a hello-world salute). Those teach the SDK. They are not a primitive another builder can take into insurance, identity, or market resolution without rewriting the hard parts.

SourceQuorum is the hard part, extracted:

1. **Typed claims** — `BINARY`, `ENUM`, `NUMERIC`. The extract prompt, the comparator, and the quorum function all change with the type.
2. **Locked source sets** — the leader cannot invent, drop, or reorder URLs. Validators reject any report list that is not exactly the locked set.
3. **Independent re-execution** — `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`. Each validator calls `gl.nondet.web.get` and `gl.nondet.exec_prompt` again. Format-only checks are rejected by construction.
4. **An UNRESOLVED gate** — if either side extracts `UNRESOLVED` and the other extracts a concrete outcome, that is a reject, not a settle. Tolerance cannot turn a missing fact into a vote.
5. **Deterministic settlement after consensus** — quorum math runs *outside* the nondet block, on the agreed extracts. Ties, coverage failures, and numeric dispersion are stored as `UNRESOLVED`, not thrown away.
6. **Challenge as an extra source** — the primitive's appeal path. A later `resolve` must re-fetch the whole expanded set.
7. **A consumer contract** — `QuorumBond` reads `get_settlement` through `gl.get_contract_at` / `@gl.contract_interface`. It never calls an LLM.

If you are building a full frontend around this, that is a Project. This submission is the contracts, the math, the tests, and the explanation.

## How consensus is used

```
create_claim → add_source* → lock_sources
        │
        ▼
   resolve()
        │
        ├─ leader_fn
        │     for url in locked_sources:
        │         page = gl.nondet.web.get(url)
        │         fact = LLM extract from THIS page only
        │
        ├─ validator_fn
        │     if leader is not Return → classify error
        │     else re-run leader_fn (extract + compute_quorum)
        │     compare reports: url set, fetch_ok, outcome, number ± bps
        │     compare settlement: status, outcome, numeric_ticks EXACT
        │
        └─ persist canonical settlement
              NUMERIC: integer ticks, not the leader's raw median
        │
        ▼
   SETTLED | UNRESOLVED
        │
        ├─ challenge(extra_url) only while challenge_open_until
        └─ finalize() only after that window → FINAL
           QuorumBond settle_bond requires FINAL
```

Full rules: [`docs/CONSENSUS.md`](docs/CONSENSUS.md).

This follows GenLayer's documented production pattern: custom `run_nondet_unsafe`, independent evidence, field-level comparison, error classification, and side effects only after consensus. It does **not** use `prompt_non_comparative` as a schema check, and it does **not** use `strict_eq` on raw LLM text.

## Contract API

### SourceQuorum

| Method | Type | Purpose |
|--------|------|---------|
| `create_claim(question, claim_type, allowed_outcomes, min_quorum, min_coverage, tolerance_bps, challenge_budget, initial_sources)` | write | Open a `DRAFT` claim |
| `add_source(claim_id, url, label)` | write | Creator only, draft only |
| `lock_sources(claim_id)` | write | Freeze the URL set |
| `resolve(claim_id)` | write | Multi-source consensus + quorum |
| `challenge(claim_id, extra_url, extra_label, reason)` | write | Add one source, reopen |
| `finalize(claim_id)` | write | Freeze after the challenge window; not callable immediately |
| `get_settlement(claim_id)` | view | **Consumer API** |
| `get_claim` / `list_claims` / `get_meta` / `describe_primitive` | view | Inspection |

`claim_type` is `BINARY`, `ENUM`, or `NUMERIC`. Sources are a JSON list or a comma-separated URL list.

### QuorumBond

| Method | Type | Purpose |
|--------|------|---------|
| `__init__(oracle_address)` | ctor | Bind to a SourceQuorum |
| `create_bond(claim_id, expected_outcome, expected_numeric_min, expected_numeric_max, beneficiary)` | payable write | Lock GEN |
| `settle_bond(bond_id)` | write | Read oracle, assign payee |
| `withdraw(bond_id)` | write | Pay once, on finalization |
| `preview_settlement(claim_id)` | view | Pass-through to the oracle |

`settle_bond` is idempotent. `withdraw` uses `emit_transfer(..., on='finalized')` so an appealed parent cannot double-pay.

## Recipes other builders can copy

**Parametric trigger.** `NUMERIC` claim, three weather or agency URLs, `min_quorum = 2`, `tolerance_bps = 200`. Bond pays if the consensus `numeric_ticks` fall inside a range.

**Public-criterion bounty.** `BINARY` question: “Does this pull request description and linked report satisfy the posted rubric?” Sources are the rubric page and the deliverable. Bond releases to the author on `YES`.

**Event resolution.** `ENUM` (`HOME,AWAY,DRAW`) with two independent sports desks plus a third challenge URL.

None of these belong in this repo as a product. They are how the primitive is meant to be used.

## Tests

Settlement math has no GenVM dependency:

```bash
node --test tests/quorum_math.node.test.js
# or, with Python on PATH:
python tests/test_quorum_math.py
```

Direct-mode contract tests (requires `genlayer-test`):

```bash
pip install -r requirements.txt
pytest tests/direct/test_source_quorum.py -v
```

What the tests cover: majority settle, ties, coverage gates, unused `UNRESOLVED` extracts, numeric median bands, numeric dispersion, excerpt-ignored equivalence, the UNRESOLVED gate, and URL-set integrity (a leader cannot swap in a different source).

## Deploy

Studio: paste [`contracts/source_quorum.py`](contracts/source_quorum.py) into [studio.genlayer.com](https://studio.genlayer.com). Then deploy `quorum_bond.py` with the oracle address as the constructor argument.

CLI:

```bash
npm install
# Studionet — ephemeral account, fund it in Studio
npm run deploy:studionet

# Bind a bond to the new oracle
node scripts/deploy.mjs studionet --with-bond

# Bradbury — funded key
PRIVATE_KEY=0x… npm run deploy:bradbury
```

Addresses are written to `deployments/source-quorum-<chainId>.json`.

## Live v1.2.0 (submit this Explorer URL)

On-chain `get_meta.version` is `1.2.0-source-quorum`. Challenge window is 24h; QuorumBond settles only from `FINAL`.

```
https://explorer-studio.genlayer.com/address/0x4c9930DC11Cad44dA46CBB3Cd5D6C73BC2fba476
```

QuorumBond (consumer): `0x19B4C3157bc73e218ffd9966f1a7c28093d33D83`  
Deploy tx: `0x985ea482cf79086df97bba2982d21e67d523a531038c42b5159ecb31c44e19c8`

Do not resubmit a v1.0.0 or v1.1.0 address.

## What this is not

- Not a hello-world, storage example, or salute generator.
- Not a thin `exec_prompt` wrapper that stores whatever the leader said.
- Not a format-only validator.
- Not a fork of the football prediction market or of a single-URL docket.
- Not a full app. There is no product flow to submit under Projects.

## License

MIT
