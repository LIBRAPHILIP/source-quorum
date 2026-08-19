# SourceQuorum — project notes

This is the submission note for the **Projects** category.

## What it does

SourceQuorum is a complete GenLayer app for **public-fact bonds**.

1. A user opens a typed public fact (`BINARY`, `ENUM`, or `NUMERIC`) and locks two or more live HTTPS sources.
2. Anyone can call `resolve`. GenLayer validators independently fetch every locked page, extract one structured fact per page, and agree on those extracts.
3. Deterministic quorum math then settles the claim. Ties, missing coverage, and numeric dispersion stay `UNRESOLVED`.
4. QuorumBond locks GEN against an expected outcome. It never calls an LLM. It reads `get_settlement` and pays only if the public record, as settled, matches.

The frontend is not a brochure. It deploys the contracts, submits `writeContract` calls, waits for `ACCEPTED` with live `getTransaction` / `getLastRoundData`, then refreshes the desk via `readContract`.

## The problem it solves

Two parties can agree that “the public record will decide” and still fight about what the record said. Today they fall back to:

- a single counterparty,
- a single URL,
- a single model,
- or an off-chain human.

That is a trust problem, not a prompting problem. SourceQuorum makes the source set explicit, makes each validator re-fetch it, and refuses to settle unless a quorum of independent pages agree.

## How to use it

1. Open the live app.
2. Choose **Studionet** (easiest) or **Bradbury**.
3. Create an **ephemeral** account and fund it in Studio, or connect a funded wallet.
4. **Deploy SourceQuorum**, then **Deploy QuorumBond**.
5. Load a template (official GenLayer docs pages) or paste your own question and two HTTPS URLs.
6. **Create claim** → **Lock sources** → **Resolve**.
7. Watch the consensus feed. After `SETTLED`, **Finalize**.
8. **Create bond** with an expected outcome (`YES`, `NO`, or `VALUE` plus a numeric range). After settlement, **Settle bond** then **Withdraw**.

Explorer evidence for the portal is the contract page:

`https://explorer-<network>.genlayer.com/address/0x<40 hex chars>`

## Why this is a Project, not a contract-only submission

- GenLayer is the main workflow, not a badge.
- There is a real product surface: desk, claim lifecycle, bond, consensus feed.
- The app calls `deployContract`, `writeContract`, `readContract`, and `waitForTransactionReceipt`.
- Continued use is obvious: public-criterion bounties, parametric triggers, announcement verification.

## What it is not

Not a hello-world. Not a thin `exec_prompt` wrapper. Not a format-only validator. Not OpenBench (that is a single-URL adjudication docket). SourceQuorum requires a locked multi-source set and pays only after quorum.
